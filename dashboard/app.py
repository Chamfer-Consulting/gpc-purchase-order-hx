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

import qbo_client  # noqa: E402 — needs the sys.path insert above
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
    datamgmt_edit,
    datamgmt_raw,
    fulfillment_dataquality,
    fulfillment_match,
    fulfillment_rvd,
    home,
    quickbooks_connection,
    quickbooks_invoices,
    reports_breakdown,
    reports_customers,
    reports_pricing,
    reports_products,
    reports_trends,
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
st.sidebar.caption("🌗 Switch Light/Dark/system theme via the ⋮ menu (top right) → Settings.")
st.sidebar.divider()

# ── Sidebar: filters ─────────────────────────────────────────────────────────────

st.sidebar.header("Filters")

min_date = invoices["effective_date"].min()
max_date = invoices["effective_date"].max()
has_dates = pd.notna(min_date) and pd.notna(max_date)

DATE_PRESETS = ["Last 30 days", "Last 90 days", "Year to date", "Year", "All time", "Custom"]
preset = st.sidebar.selectbox("Date range", DATE_PRESETS, index=4, key="date_preset")

if has_dates:
    today = pd.Timestamp(max_date.date())
    if preset == "Last 30 days":
        start_ts, end_ts = today - pd.Timedelta(days=29), today
    elif preset == "Last 90 days":
        start_ts, end_ts = today - pd.Timedelta(days=89), today
    elif preset == "Year to date":
        start_ts, end_ts = pd.Timestamp(year=today.year, month=1, day=1), today
    elif preset == "Year":
        year_options = sorted(invoices["effective_date"].dt.year.dropna().unique().astype(int).tolist(), reverse=True)
        picked_year = st.sidebar.selectbox("Year", year_options, key="filter_year")
        start_ts = pd.Timestamp(year=picked_year, month=1, day=1)
        end_ts = pd.Timestamp(year=picked_year, month=12, day=31)
    elif preset == "All time":
        start_ts, end_ts = min_date, max_date
    else:  # Custom
        custom_range = st.sidebar.date_input(
            "Custom range", value=(min_date.date(), max_date.date()), key="custom_range",
        )
        if isinstance(custom_range, tuple) and len(custom_range) == 2:
            start_ts, end_ts = pd.Timestamp(custom_range[0]), pd.Timestamp(custom_range[1])
        else:
            start_ts, end_ts = min_date, max_date
else:
    start_ts, end_ts = None, None

customers = sorted(invoices["customer_name"].dropna().unique().tolist())
selected_customers = st.sidebar.multiselect("Customer", customers, default=[], key="filter_customers")

hidden_products = load_hidden_products()

products = sorted(
    set(inv_items_all.loc[inv_items_all["category"] == "product", "product_name"].dropna().unique().tolist())
    - hidden_products
)
selected_products = st.sidebar.multiselect("Product", products, default=[], key="filter_products")
if hidden_products:
    st.sidebar.caption(f"🙈 {len(hidden_products)} product(s) hidden — manage on the Products report page.")

include_samples = st.sidebar.checkbox("Include samples", value=False, key="include_samples")

fc1, fc2 = st.sidebar.columns(2)
if fc1.button("🔄 Refresh data"):
    load_data.clear()
    st.rerun()
if fc2.button("✖️ Clear filters"):
    for key in ("filter_customers", "filter_products", "date_preset", "filter_year", "custom_range", "include_samples"):
        st.session_state.pop(key, None)
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

if hidden_products:
    f_inv_items = f_inv_items[~f_inv_items["product_name"].isin(hidden_products)]

# Delivery/donation/service/other aren't produce at all — always excluded from
# product-facing invoice reports. "product" and "sample" are separate categories
# (see classify_qbo_item); keep both here so the "Include samples" toggle below still
# has something to act on, matching the existing PO-side behavior.
f_inv_items = f_inv_items[f_inv_items["category"].isin(["product", "sample"])]

if not include_samples:
    f_inv_items = f_inv_items[~f_inv_items["is_sample"]]

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
    hidden_products=hidden_products,
    by_product=by_product,
    by_customer=by_customer,
    by_product_inv=by_product_inv,
    by_customer_inv=by_customer_inv,
    product_colors=product_colors,
)

# ── Navigation ────────────────────────────────────────────────────────────────────
# A flat st.navigation sidebar replaces the former double-nested st.tabs — only the
# active page's render(ctx) call below executes per rerun (vs. every sub-tab body
# executing on every rerun under the old st.tabs structure).
#
# Each st.Page callable is a lambda closing over `ctx` by name, not by value — Python
# resolves that reference only when the lambda actually runs (i.e. when the page is
# navigated to), by which point `ctx.pages` below has already been populated. That's
# what makes the apparent circularity here safe: page objects need `ctx` to render,
# and `ctx.pages` needs the page objects for Home's "Needs attention" deep links —
# neither is actually evaluated until well after both exist.

page_home = st.Page(lambda: home.render(ctx), title="Home", icon="🏠", url_path="home", default=True)
page_trends = st.Page(lambda: reports_trends.render(ctx), title="Trends", url_path="trends")
page_products = st.Page(lambda: reports_products.render(ctx), title="Products", url_path="products")
page_customers = st.Page(lambda: reports_customers.render(ctx), title="Customers", url_path="customers")
page_breakdown = st.Page(lambda: reports_breakdown.render(ctx), title="Breakdown", url_path="breakdown")
page_pricing = st.Page(
    lambda: reports_pricing.render(ctx), title="Pricing & Reference Prices", icon="🏷️", url_path="pricing"
)
page_match_review = st.Page(lambda: fulfillment_match.render(ctx), title="Match & Review", icon="🔗", url_path="match_review")
page_rvd = st.Page(
    lambda: fulfillment_rvd.render(ctx), title="Requested vs Delivered", url_path="requested_vs_delivered"
)
page_data_quality = st.Page(
    lambda: fulfillment_dataquality.render(ctx), title="Data Quality", icon="⚠️", url_path="data_quality"
)
page_raw_data = st.Page(lambda: datamgmt_raw.render(ctx), title="Raw Data", url_path="raw_data")
page_edit_po = st.Page(lambda: datamgmt_edit.render(ctx), title="Edit PO", icon="✏️", url_path="edit_po")
page_qbo_connection = st.Page(
    lambda: quickbooks_connection.render(ctx), title="Connection & Sync", url_path="qbo_connection"
)
page_qbo_invoices = st.Page(lambda: quickbooks_invoices.render(ctx), title="Invoice Explorer", url_path="qbo_invoices")

pages = {
    "": [page_home],
    "📊 Reports": [page_trends, page_products, page_customers, page_breakdown, page_pricing],
    "📦 Fulfillment": [page_match_review, page_rvd, page_data_quality],
    "🗂️ Data Management": [page_raw_data, page_edit_po],
    "🔗 QuickBooks": [page_qbo_connection, page_qbo_invoices],
}

# Subset of pages dashboard/attention.py's AttentionItem.page values reference —
# keyed the same as those strings so Home's digest can st.page_link(ctx.pages[...]).
ctx.pages = {
    "data_quality": page_data_quality,
    "match_review": page_match_review,
    "requested_vs_delivered": page_rvd,
}

st.title("🌱 Garfield Produce — Purchase Order Dashboard")
nav = st.navigation(pages)
nav.run()
