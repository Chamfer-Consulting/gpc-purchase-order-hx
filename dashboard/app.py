#!/usr/bin/env python3
"""
Garfield Produce Company — PO Dashboard

Composition root: auth gate, QuickBooks OAuth callback, data loading, sidebar filters,
then hands off to st.navigation for page routing. Page bodies live in
dashboard/views/*.py (Phase 1 of the nav/UI overhaul —
see /Users/jcaternolo/.claude/plans/golden-soaring-robin.md). This mirrors the former
monolithic app.py's control flow exactly (same order: OAuth callback -> password gate
-> data load -> sidebar filters -> render), just with page bodies extracted out.

Run locally with:  streamlit run dashboard/app.py   (from the repo root)
"""

import os
import secrets
import sys

import pandas as pd
import psycopg2
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import filters  # noqa: E402 — dashboard-local, needs the sys.path insert above
import gmail_client  # noqa: E402
import qbo_client  # noqa: E402
import theme  # noqa: E402
from data import (  # noqa: E402
    DARK,
    LIGHT,
    AppContext,
    color_map_for,
    get_database_url,
    load_data,
    load_hidden_products,
    load_invoice_data,
    prepare,
    prepare_invoices,
)
from views import (  # noqa: E402
    customer_360,
    explore,
    fulfillment_dataquality,
    fulfillment_rvd,
    home,
    match_reconcile,
    reports_products,
    settings,
)

st.set_page_config(page_title="Garfield Produce — PO Dashboard", layout="wide", page_icon="🌱")

# ── QuickBooks OAuth callback ─────────────────────────────────────────────────────
# Handled before the password gate: a full-page browser redirect back from Intuit may
# or may not preserve session_state["authed"], and completing a token exchange that
# only the account owner could have triggered (by clicking Connect from inside the
# password-gated app) isn't a meaningful security exposure either way.

_qp = st.query_params
if "code" in _qp and "realmId" in _qp:
    try:
        _conn = psycopg2.connect(get_database_url())
        try:
            qbo_client.exchange_code_for_tokens(_conn, _qp["code"], _qp["realmId"])
        finally:
            _conn.close()
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        # A failed exchange (stale/reused code, double-submit, etc.) must not crash the
        # whole app — clear the bad query params and fall through to the normal app
        # below instead of leaving the user stuck on a dead error screen.
        st.query_params.clear()
        st.error(f"QuickBooks connection failed: {e}\n\nYou can try **Connect to QuickBooks** again from the 🔗 QuickBooks pages.")
elif "code" in _qp and _qp.get("state", "").startswith("gmail_connect"):
    # Google's callback never carries realmId, so this can't collide with the QBO
    # branch above — see email_ingestion.py's state prefixing.
    try:
        _conn = psycopg2.connect(get_database_url())
        try:
            gmail_client.exchange_code_for_tokens(
                _conn, st.secrets["gmail_client_id"], st.secrets["gmail_client_secret"],
                st.secrets["gmail_redirect_uri"], _qp["code"],
            )
        finally:
            _conn.close()
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        st.error(f"Gmail connection failed: {e}\n\nYou can try **Connect Gmail** again from the ✉️ Email Ingestion page.")

# ── Auth ────────────────────────────────────────────────────────────────────────


def check_password() -> bool:
    if st.session_state.get("authed"):
        return True
    st.title("🌱 Garfield Produce — PO Dashboard")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        expected = st.secrets.get("dashboard_password", "")
        if expected and secrets.compare_digest(pw, expected):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()

# ── Data loading ────────────────────────────────────────────────────────────────

po_df, items_df, matched_df = load_data()

if po_df.empty:
    st.info("No data yet — run `python sync_dashboard.py` after your first extraction batch.")
    st.stop()

valid_po, latest_po, all_items, latest_items = prepare(po_df, items_df)

inv_df, inv_items_df = load_invoice_data()
invoices, inv_items_all = prepare_invoices(inv_df, inv_items_df)

# ── Sidebar: appearance ──────────────────────────────────────────────────────────
# Theme is Streamlit's own native Light/Dark/"Use system setting" (⋮ menu → Settings)
# so every built-in widget — tables, data_editor, buttons, inputs, alerts — is themed
# correctly and consistently, not just the few containers a hand-rolled CSS override
# could reach. We only need to know which one is active so charts (Plotly renders a
# static spec, it can't inherit Streamlit's CSS) pick the matching validated palette.
theme_type = (st.context.theme.type if st.context.theme else None) or "light"
palette = DARK if theme_type == "dark" else LIGHT
theme.inject(theme_type)
st.sidebar.caption("🌗 Switch Light/Dark/system theme via the ⋮ menu (top right) → Settings.")

# ── Filters: comprehensive top bar (replaces the former sidebar block) ─────────────
# Redesign spec §03 / decision #2. filters.render_filter_bar() draws the sticky bar
# in the main area (above every page's body) and returns a FilterState; the mapping
# below feeds AppContext exactly where the old sidebar code did. selected_sizes,
# compare_mode/prev_* and line_types are new — carried on ctx for the pages that
# will consume them in later phases; the invoice-category filter still matches the
# old ["product","sample"] behaviour until the views are ready for it (Phase C).

st.title("🌱 Garfield Produce — Purchase Order Dashboard")

min_date = invoices["effective_date"].min()
max_date = invoices["effective_date"].max()

hidden_products = load_hidden_products()
customers = sorted(invoices["customer_name"].dropna().unique().tolist())
products = sorted(
    set(inv_items_all.loc[inv_items_all["category"] == "product", "product_name"].dropna().unique().tolist())
    - hidden_products
)
sizes = sorted(
    inv_items_all.loc[inv_items_all["category"] == "product", "container_size"].dropna().unique().tolist()
)

fs = filters.render_filter_bar(min_date, max_date, customers, products, sizes)
start_ts, end_ts = fs.start_ts, fs.end_ts
selected_customers = fs.selected_customers
selected_products = fs.selected_products
selected_sizes = fs.selected_sizes
include_samples = fs.include_samples

if hidden_products:
    st.sidebar.caption(f"🙈 {len(hidden_products)} product(s) hidden — manage on the Products report page.")
if st.sidebar.button("🔄 Refresh data"):
    load_data.clear()
    st.rerun()

# Apply filters
f_po = latest_po.copy()
f_items = latest_items.copy()

if start_ts is not None and end_ts is not None:
    f_po = f_po[(f_po["effective_date"] >= start_ts) & (f_po["effective_date"] <= end_ts)]
    f_items = f_items[f_items["po_id"].isin(f_po["id"])]

if selected_customers:
    f_po = f_po[f_po["customer_name"].isin(selected_customers)]
    f_items = f_items[f_items["po_id"].isin(f_po["id"])]

if selected_products:
    f_items = f_items[f_items["product_name"].isin(selected_products)]

if selected_sizes:
    f_items = f_items[f_items["container_size"].isin(selected_sizes)]

if hidden_products:
    f_items = f_items[~f_items["product_name"].isin(hidden_products)]

if not include_samples:
    f_items = f_items[~f_items["is_sample"]]

# Same filters applied to the invoice-based universe — this is what Reports is built
# from (see the "make QBO invoices the primary source" rework); f_po/f_items above
# remain PO-scoped for the pages that are inherently about PO<->invoice comparison or
# the extraction pipeline's own data quality.
f_inv = invoices.copy()
f_inv_items = inv_items_all.copy()

if start_ts is not None and end_ts is not None:
    f_inv = f_inv[(f_inv["effective_date"] >= start_ts) & (f_inv["effective_date"] <= end_ts)]
    f_inv_items = f_inv_items[f_inv_items["invoice_id"].isin(f_inv["id"])]

if selected_customers:
    f_inv = f_inv[f_inv["customer_name"].isin(selected_customers)]
    f_inv_items = f_inv_items[f_inv_items["invoice_id"].isin(f_inv["id"])]

if selected_products:
    f_inv_items = f_inv_items[f_inv_items["product_name"].isin(selected_products)]

if selected_sizes:
    f_inv_items = f_inv_items[f_inv_items["container_size"].isin(selected_sizes)]

if hidden_products:
    f_inv_items = f_inv_items[~f_inv_items["product_name"].isin(hidden_products)]

# f_inv_lines keeps EVERY line-type the filter bar's "line type" control has
# checked (Sales=product, Donations, Shipping=delivery, …) — used by Overview to
# split revenue from donations/shipping (redesign decision #1) and by Customer 360
# later. f_inv_items stays product(+sample) only, so the existing product/customer
# analytical pages are unchanged.
f_inv_lines = f_inv_items[f_inv_items["category"].isin(fs.categories)] if fs.categories else f_inv_items.iloc[0:0]

f_inv_items = f_inv_items[f_inv_items["category"].isin(["product", "sample"])]

if not include_samples:
    f_inv_items = f_inv_items[~f_inv_items["is_sample"]]
    f_inv_lines = f_inv_lines[~f_inv_lines["is_sample"]]

product_colors = color_map_for(
    set(inv_items_all.loc[inv_items_all["category"] == "product", "product_name"].dropna().unique().tolist())
    - hidden_products,
    palette,
)

# Precomputed once so multiple pages can reuse them.
if f_items.empty:
    by_product = pd.DataFrame(columns=["product_name", "revenue", "quantity"])
else:
    by_product = (
        f_items.groupby("product_name").agg(revenue=("line_total", "sum"), quantity=("quantity", "sum")).reset_index()
    )

if f_po.empty:
    by_customer = pd.DataFrame(columns=["customer_name", "orders", "revenue", "avg_order_value"])
else:
    by_customer = (
        f_po.groupby("customer_name").agg(orders=("id", "nunique"), revenue=("total", "sum")).reset_index()
    )
    by_customer["avg_order_value"] = (by_customer["revenue"] / by_customer["orders"]).round(2)

# Invoice-based equivalents — same shape, source is f_inv/f_inv_items (the full
# customer/product universe) instead of the PO-only f_po/f_items above.
if f_inv_items.empty:
    by_product_inv = pd.DataFrame(columns=["product_name", "revenue", "quantity"])
else:
    by_product_inv = (
        f_inv_items.groupby("product_name").agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
        .reset_index()
    )

if f_inv.empty:
    by_customer_inv = pd.DataFrame(columns=["customer_name", "invoices", "revenue", "avg_invoice_value"])
else:
    by_customer_inv = (
        f_inv.groupby("customer_name").agg(invoices=("id", "nunique"), revenue=("total_amt", "sum")).reset_index()
    )
    by_customer_inv["avg_invoice_value"] = (by_customer_inv["revenue"] / by_customer_inv["invoices"]).round(2)

ctx = AppContext(
    palette=palette,
    theme_type=theme_type,
    start_ts=start_ts,
    end_ts=end_ts,
    selected_customers=selected_customers,
    selected_products=selected_products,
    include_samples=include_samples,
    fs=fs,
    selected_sizes=selected_sizes,
    compare_mode=fs.compare_mode,
    prev_start=fs.prev_start,
    prev_end=fs.prev_end,
    line_types=fs.line_types,
    po_df=po_df,
    valid_po=valid_po,
    latest_po=latest_po,
    all_items=all_items,
    invoices=invoices,
    inv_items_all=inv_items_all,
    f_po=f_po,
    f_items=f_items,
    f_inv=f_inv,
    f_inv_items=f_inv_items,
    f_inv_lines=f_inv_lines,
    hidden_products=hidden_products,
    by_product=by_product,
    by_customer=by_customer,
    by_product_inv=by_product_inv,
    by_customer_inv=by_customer_inv,
    product_colors=product_colors,
)

# ── Navigation ────────────────────────────────────────────────────────────────────
# Redesign spec §03: 8 destinations in two tiers — "Analyse" (read the business) and
# "Operate" (fix and configure). Explore folds in the former Trends + Breakdown +
# Compare-periods; Settings and Match & Reconcile lazily host the former Data
# Management / QuickBooks / Email pages behind a segmented control. url_path values
# are kept where a page carried one so old bookmarks still resolve.
#
# Each st.Page callable is a lambda closing over `ctx` by name (resolved only when
# the page runs), so ctx.pages below — populated right after — is available for
# Home's "Needs attention" deep links.

page_overview = st.Page(lambda: home.render(ctx), title="Overview", icon="🏠", url_path="home", default=True)
page_customers = st.Page(lambda: customer_360.render(ctx), title="Customer 360", icon="👥", url_path="customers")
page_products = st.Page(lambda: reports_products.render(ctx), title="Products & Sizes", icon="🥬", url_path="products")
page_explore = st.Page(lambda: explore.render(ctx), title="Explore", icon="🔎", url_path="explore")
page_lifecycle = st.Page(
    lambda: fulfillment_rvd.render(ctx), title="Order Lifecycle", icon="🔄", url_path="requested_vs_delivered"
)
page_data_quality = st.Page(
    lambda: fulfillment_dataquality.render(ctx), title="Data Quality", icon="⚠️", url_path="data_quality"
)
page_match = st.Page(lambda: match_reconcile.render(ctx), title="Match & Reconcile", icon="🔗", url_path="match_review")
page_settings = st.Page(lambda: settings.render(ctx), title="Settings & Connections", icon="⚙️", url_path="settings")

pages = {
    "Analyse": [page_overview, page_customers, page_products, page_explore, page_lifecycle],
    "Operate": [page_data_quality, page_match, page_settings],
}

# Keys match dashboard/attention.py's AttentionItem.page values so Home's digest can
# st.page_link(ctx.pages[...]). "requested_vs_delivered" now points at Order Lifecycle.
ctx.pages = {
    "data_quality": page_data_quality,
    "match_review": page_match,
    "requested_vs_delivered": page_lifecycle,
}

nav = st.navigation(pages)
nav.run()
