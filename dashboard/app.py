#!/usr/bin/env python3
"""
Garfield Produce Company — PO Dashboard

Reads from the hosted Postgres database populated by sync_dashboard.py.
Run locally with:  streamlit run dashboard/app.py   (from the repo root)
"""

import io
import os
import secrets
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from math_check import validate_math  # noqa: E402 — needs the sys.path insert above

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qbo_client  # noqa: E402 — needs the sys.path insert above (AppTest doesn't add the script's own dir like `streamlit run` does)
import qbo_matcher  # noqa: E402
import gdrive_client  # noqa: E402

st.set_page_config(page_title="Garfield Produce — PO Dashboard", layout="wide", page_icon="🌱")

# ── Palette (validated colorblind-safe set — see dataviz skill / schema.sql sibling) ──
# Both Light and Dark are selected palettes from the same reference instance, not an
# automatic flip — same categorical order, dark-surface steps, per the skill's palette.md.
LIGHT = {
    "categorical": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "sequential_blue": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
    "ink_primary": "#0b0b0b",
    "ink_muted": "#898781",
    "grid": "#e1e0d9",
    "surface": "#fcfcfb",
    "page_plane": "#f9f9f7",
}
DARK = {
    "categorical": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    "sequential_blue": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
    "ink_primary": "#ffffff",
    "ink_muted": "#898781",
    "grid": "#2c2c2a",
    "surface": "#1a1a19",
    "page_plane": "#0d0d0d",
}

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def style(fig: go.Figure, palette: dict) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=palette["surface"],
        plot_bgcolor=palette["surface"],
        font=dict(color=palette["ink_primary"], family=FONT_FAMILY),
        xaxis=dict(gridcolor=palette["grid"], linecolor=palette["ink_muted"], zeroline=False),
        yaxis=dict(gridcolor=palette["grid"], linecolor=palette["ink_muted"], zeroline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor=palette["surface"], font_family=FONT_FAMILY),
    )
    return fig


def color_map_for(categories: list[str], palette: dict) -> dict:
    """Fixed hue per category (alphabetical order) so a category keeps its color
    across every chart and across filter changes — never repainted."""
    ordered = sorted(categories)
    cat_colors = palette["categorical"]
    colors = {}
    for i, cat in enumerate(ordered):
        colors[cat] = cat_colors[i] if i < len(cat_colors) else palette["ink_muted"]
    return colors


def fmt_delta(value, prefix: str = "", decimals: int = 0):
    """Formats a KPI delta for st.metric, or returns None (no delta shown) if unavailable."""
    if value is None or pd.isna(value):
        return None
    return f"{prefix}{value:+,.{decimals}f}"


def strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Excel can't hold timezone-aware datetimes — Postgres TIMESTAMPTZ columns
    (e.g. extracted_at) come back tz-aware from psycopg2; drop the tz for export."""
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_localize(None)
    return df


def month_over_month_movers(df: pd.DataFrame, date_col: str, group_col: str, value_col: str, top_n: int = 8):
    """Compares the two most recent distinct months present in df, grouped by group_col.
    Returns (movers_df, current_month, previous_month), or None if fewer than 2 months exist."""
    d = df.dropna(subset=[date_col, group_col]).copy()
    if d.empty:
        return None
    d["month"] = d[date_col].dt.to_period("M")
    months = sorted(d["month"].unique())
    if len(months) < 2:
        return None
    curr_m, prev_m = months[-1], months[-2]
    curr = d[d["month"] == curr_m].groupby(group_col)[value_col].sum()
    prev = d[d["month"] == prev_m].groupby(group_col)[value_col].sum()
    merged = pd.DataFrame({"prev": prev, "curr": curr}).fillna(0.0)
    merged["delta"] = merged["curr"] - merged["prev"]
    merged = merged.reindex(merged["delta"].abs().sort_values(ascending=False).index).head(top_n)
    merged = merged.reset_index().rename(columns={"index": group_col})
    merged["Change"] = merged["delta"].apply(lambda v: f"▲ +${v:,.0f}" if v >= 0 else f"▼ -${abs(v):,.0f}")
    return merged, curr_m, prev_m


def yoy_annual_chart(df: pd.DataFrame, date_col: str, agg_col: str, agg_fn: str, y_label: str, palette: dict, current_year: str):
    """Line chart with one line per calendar year (month-of-year on the x-axis),
    current_year emphasized (bold, full opacity) against past years (thin, dotted,
    muted) for an at-a-glance annual comparison. Returns None if there's no dated data."""
    src = df.dropna(subset=[date_col]).copy()
    if src.empty:
        return None
    src["year"] = src[date_col].dt.year.astype(str)
    src["moy"] = src[date_col].dt.month
    if agg_fn == "nunique":
        grouped = src.groupby(["year", "moy"])[agg_col].nunique().reset_index(name="value")
    else:
        grouped = src.groupby(["year", "moy"])[agg_col].sum().reset_index(name="value")
    if grouped.empty:
        return None

    year_colors = color_map_for(grouped["year"].unique().tolist(), palette)
    fig = px.line(
        grouped, x="moy", y="value", color="year", markers=True,
        color_discrete_map=year_colors, labels={"moy": "", "value": y_label, "year": "Year"},
    )
    fig.update_xaxes(
        tickmode="array", tickvals=list(range(1, 13)),
        ticktext=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    )
    for trace in fig.data:
        if trace.name == current_year:
            trace.update(line=dict(width=4), opacity=1.0, marker=dict(size=8))
        else:
            trace.update(line=dict(width=1.5, dash="dot"), opacity=0.55, marker=dict(size=5))
    return fig


def get_database_url() -> str:
    url = st.secrets.get("database_url") or os.environ.get("DATABASE_URL")
    if not url:
        st.error("No database configured. Set `database_url` in .streamlit/secrets.toml.")
        st.stop()
    return url


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
        st.error(f"QuickBooks connection failed: {e}\n\nYou can try **Connect to QuickBooks** again from the QuickBooks tab.")

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
        if expected and pw == expected:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()

# ── Data loading ────────────────────────────────────────────────────────────────

def save_po_edit(po_id: int, header: dict, items: list[dict]) -> None:
    """Writes a manual edit straight to Postgres and marks the PO as edited so
    sync_dashboard.py never overwrites it again (see its ON CONFLICT ... WHERE clause)."""
    data = {"subtotal": header["subtotal"], "tax": header["tax"], "total": header["total"], "line_items": items}
    validate_math(data)

    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE purchase_orders SET
                    po_number = %(po_number)s, customer_name = %(customer_name)s,
                    po_date = %(po_date)s, delivery_date = %(delivery_date)s,
                    subtotal = %(subtotal)s, tax = %(tax)s, total = %(total)s, notes = %(notes)s,
                    math_check_failed = %(math_check_failed)s, math_check_detail = %(math_check_detail)s,
                    edited = TRUE, edited_at = now()
                WHERE id = %(po_id)s
                """,
                {**header, "po_id": po_id,
                 "math_check_failed": data["math_check_failed"], "math_check_detail": data["math_check_detail"]},
            )
            cur.execute("DELETE FROM line_items WHERE po_id = %s", (po_id,))
            for item in items:
                cur.execute(
                    """
                    INSERT INTO line_items (
                        po_id, product_raw, product_name, container_size,
                        quantity, unit_price, line_total, is_sample,
                        math_mismatch, revision_status, is_removed
                    ) VALUES (
                        %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
                        %(quantity)s, %(unit_price)s, %(line_total)s, %(is_sample)s,
                        %(math_mismatch)s, 'Edited', FALSE
                    )
                    """,
                    {
                        "po_id": po_id,
                        "product_raw": item.get("product_name"),
                        "product_name": item.get("product_name"),
                        "container_size": item.get("container_size"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("unit_price"),
                        "line_total": item.get("line_total"),
                        "is_sample": bool(item.get("is_sample", False)),
                        "math_mismatch": item.get("math_mismatch"),
                    },
                )
        conn.commit()
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner="Loading PO data...")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conn = psycopg2.connect(get_database_url())
    try:
        po_df = pd.read_sql_query("SELECT * FROM purchase_orders", conn)
        items_df = pd.read_sql_query("SELECT * FROM line_items", conn)
        # One row per CONFIRMED PO<->invoice match — the only pairs anyone has actually
        # verified, not just an algorithm's guess. Powers "requested vs. delivered" views.
        matched_df = pd.read_sql_query(
            """
            SELECT po.id AS po_id, po.po_number, po.source_file, po.customer_name AS po_customer,
                   po.po_date, po.sent_date, po.total AS po_total,
                   inv.id AS invoice_id, inv.doc_number, inv.txn_date, inv.total_amt AS invoice_total
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
    finally:
        conn.close()
    return po_df, items_df, matched_df


@st.cache_data(ttl=300, show_spinner="Loading QuickBooks invoice data...")
def load_invoice_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The full QuickBooks invoice history — every customer, not just the 3 with PO
    documents. This is what makes Overview/Trends/Products/Customers reflect the whole
    business rather than the PO-covered slice of it."""
    conn = psycopg2.connect(get_database_url())
    try:
        inv_df = pd.read_sql_query(
            "SELECT id, doc_number, customer_name, txn_date, ship_date, total_amt, "
            "private_note FROM qbo_invoices",
            conn,
        )
        inv_items_df = pd.read_sql_query(
            "SELECT ii.invoice_id, ii.product_name, ii.container_size, ii.category, "
            "ii.is_sample, ii.quantity, ii.unit_price, ii.line_total, "
            "inv.customer_name, inv.txn_date "
            "FROM qbo_invoice_items ii JOIN qbo_invoices inv ON inv.id = ii.invoice_id",
            conn,
        )
    finally:
        conn.close()
    return inv_df, inv_items_df


def prepare_invoices(inv_df: pd.DataFrame, inv_items_df: pd.DataFrame):
    """Excludes voided invoices — same heuristic as qbo_matcher._VOID_SQL (null/zero
    total, or a private note mentioning void) — and derives effective_date."""
    inv = inv_df[
        inv_df["total_amt"].notna() & (inv_df["total_amt"] != 0)
        & ~inv_df["private_note"].fillna("").str.contains("void", case=False)
    ].copy()
    inv["effective_date"] = pd.to_datetime(inv["txn_date"], errors="coerce")

    items = inv_items_df.merge(inv[["id"]], left_on="invoice_id", right_on="id")
    items["effective_date"] = pd.to_datetime(items["txn_date"], errors="coerce")
    return inv, items


_MATCHED_ITEMS_COLUMNS = [
    "po_id", "invoice_id", "customer_name", "effective_date",
    "product_name", "container_size", "requested_qty", "requested_amount",
    "delivered_qty", "delivered_amount", "po_math_note",
]


@st.cache_data(ttl=300, show_spinner="Loading requested vs. delivered detail...")
def load_matched_line_items() -> pd.DataFrame:
    """Line-item-level requested-vs-delivered detail for every CONFIRMED PO<->invoice
    match — one row per (po_id, invoice_id, product, size). PO and invoice line items
    aren't linked 1:1 (only the PO<->invoice pair is), so this reconstructs the
    comparison: group each side's items by (id, product, size), then outer-merge the two
    groupings so a product requested-but-not-delivered (or vice versa) gets its own row
    with a zero on the missing side, instead of only surfacing the overlap."""
    conn = psycopg2.connect(get_database_url())
    try:
        links = pd.read_sql_query(
            """
            SELECT l.po_id, l.invoice_id, po.customer_name, po.po_date, po.sent_date
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
        if links.empty:
            return pd.DataFrame(columns=_MATCHED_ITEMS_COLUMNS)

        po_ids = links["po_id"].unique().tolist()
        invoice_ids = links["invoice_id"].unique().tolist()
        po_items = pd.read_sql_query(
            "SELECT po_id, product_name, container_size, quantity, line_total, math_mismatch "
            "FROM line_items "
            "WHERE po_id = ANY(%(ids)s) AND is_sample = FALSE AND is_removed = FALSE",
            conn, params={"ids": po_ids},
        )
        inv_items = pd.read_sql_query(
            "SELECT invoice_id, product_name, container_size, quantity, line_total FROM qbo_invoice_items "
            "WHERE invoice_id = ANY(%(ids)s) AND is_sample = FALSE AND category = 'product'",
            conn, params={"ids": invoice_ids},
        )
    finally:
        conn.close()

    links["effective_date"] = pd.to_datetime(links["sent_date"], errors="coerce").fillna(
        pd.to_datetime(links["po_date"], errors="coerce")
    )
    links = links[["po_id", "invoice_id", "customer_name", "effective_date"]]

    po_grouped = po_items.groupby(["po_id", "product_name", "container_size"], as_index=False).agg(
        requested_qty=("quantity", "sum"), requested_amount=("line_total", "sum"),
        po_math_note=("math_mismatch", lambda s: next((x for x in s if x), None)),
    )
    inv_grouped = inv_items.groupby(["invoice_id", "product_name", "container_size"], as_index=False).agg(
        delivered_qty=("quantity", "sum"), delivered_amount=("line_total", "sum"),
    )

    po_side = links.merge(po_grouped, on="po_id", how="left")
    inv_side = links.merge(inv_grouped, on="invoice_id", how="left")

    combined = pd.merge(
        po_side, inv_side,
        on=["po_id", "invoice_id", "customer_name", "effective_date", "product_name", "container_size"],
        how="outer",
    )
    for col in ("requested_qty", "requested_amount", "delivered_qty", "delivered_amount"):
        combined[col] = combined[col].fillna(0.0)
    return combined[_MATCHED_ITEMS_COLUMNS]


@st.cache_data(ttl=300, show_spinner="Loading reference prices...")
def load_reference_prices() -> pd.DataFrame:
    conn = psycopg2.connect(get_database_url())
    try:
        df = pd.read_sql_query(
            "SELECT id, customer_name, product_name, container_size, price, source, edited, edited_at, updated_at "
            "FROM reference_prices ORDER BY customer_name, product_name, container_size",
            conn,
        )
    finally:
        conn.close()
    return df


def save_reference_prices(rows: list[dict]) -> None:
    """Upserts each row straight to Postgres and marks it edited=TRUE so the next
    sync_dashboard.py run never overwrites it — same guard shape as save_po_edit()."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO reference_prices (customer_name, product_name, container_size, price, source, edited, edited_at)
                    VALUES (%(customer_name)s, %(product_name)s, %(container_size)s, %(price)s, 'manual', TRUE, now())
                    ON CONFLICT (customer_name, product_name, container_size) DO UPDATE SET
                        price = EXCLUDED.price, source = 'manual', edited = TRUE, edited_at = now()
                    """,
                    row,
                )
        conn.commit()
    finally:
        conn.close()


def prepare(po_df: pd.DataFrame, items_df: pd.DataFrame):
    """Dedupe to the latest version of each PO and join line items to it."""
    po = po_df.copy()
    po["po_key"] = po["po_number"].fillna(po["source_file"])
    po["po_date"] = pd.to_datetime(po["po_date"], errors="coerce")
    po["delivery_date"] = pd.to_datetime(po["delivery_date"], errors="coerce")
    po["effective_date"] = pd.to_datetime(po["sent_date"], errors="coerce").fillna(po["po_date"])

    valid_po = po[po["error"].isna()].copy()
    latest_po = (
        valid_po.sort_values(["po_key", "effective_date", "id"])
        .groupby("po_key", as_index=False)
        .tail(1)
        .copy()
    )

    items = items_df.merge(
        po[["id", "po_number", "po_key", "effective_date", "customer_name", "is_revision", "version_label", "error"]],
        left_on="po_id", right_on="id", suffixes=("", "_po"),
    )
    latest_items = items[items["po_id"].isin(latest_po["id"]) & (~items["is_removed"])].copy()

    return valid_po, latest_po, items, latest_items


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

products = sorted(
    inv_items_all.loc[inv_items_all["category"] == "product", "product_name"].dropna().unique().tolist()
)
selected_products = st.sidebar.multiselect("Product", products, default=[], key="filter_products")

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

if not include_samples:
    f_items = f_items[~f_items["is_sample"]]

# Same filters applied to the invoice-based universe — this is what Overview/Trends/
# Products/Customers are built from (see the "make QBO invoices the primary source"
# rework); f_po/f_items above remain PO-scoped for the tabs that are inherently about
# PO<->invoice comparison or the extraction pipeline's own data quality.
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

# Delivery/donation/service/other aren't produce at all — always excluded from
# product-facing invoice reports. "product" and "sample" are separate categories
# (see classify_qbo_item); keep both here so the "Include samples" toggle below still
# has something to act on, matching the existing PO-side behavior.
f_inv_items = f_inv_items[f_inv_items["category"].isin(["product", "sample"])]

if not include_samples:
    f_inv_items = f_inv_items[~f_inv_items["is_sample"]]

product_colors = color_map_for(
    inv_items_all.loc[inv_items_all["category"] == "product", "product_name"].dropna().unique().tolist(), palette
)

# Precomputed once so both their own tab and the Overview export can use them.
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

st.title("🌱 Garfield Produce — Purchase Order Dashboard")

tab_reports, tab_fulfillment, tab_datamgmt, tab_qbo = st.tabs(
    ["📊 Reports", "📦 PO Fulfillment", "🗂️ Data Management", "🔗 QuickBooks"]
)

with tab_reports:
    st.caption(
        "Reflects the full QuickBooks invoice history — every customer, not just the "
        "ones with formal PO documents. Respects the sidebar filters above."
    )
    r_overview, r_trends, r_products, r_customers, r_pricing, r_ref_prices = st.tabs(
        ["Overview", "Trends", "Products", "Customers", "Pricing", "🏷️ Reference Prices"]
    )

with tab_fulfillment:
    pf_match, pf_rvd, pf_revisions = st.tabs(
        ["🔗 Match", "Requested vs Delivered", "⚠️ Revisions & Data Quality"]
    )

with tab_datamgmt:
    dm_raw, dm_edit = st.tabs(["Raw Data", "✏️ Edit"])

# ── Reports: Overview ────────────────────────────────────────────────────────────

with r_overview:
    total_invoices = f_inv["id"].nunique()
    total_revenue = f_inv["total_amt"].sum()
    unique_customers = f_inv["customer_name"].nunique()
    distinct_products = f_inv_items.loc[f_inv_items["category"] == "product", "product_name"].nunique()
    avg_invoice_value = f_inv["total_amt"].mean() if total_invoices else 0

    delta_invoices = delta_revenue = delta_aiv = None
    if start_ts is not None and end_ts is not None:
        span = end_ts - start_ts
        prev_end = start_ts - pd.Timedelta(days=1)
        prev_start = prev_end - span
        prev_inv = invoices[(invoices["effective_date"] >= prev_start) & (invoices["effective_date"] <= prev_end)]
        if selected_customers:
            prev_inv = prev_inv[prev_inv["customer_name"].isin(selected_customers)]
        prev_count = prev_inv["id"].nunique()
        if prev_count:
            delta_invoices = total_invoices - prev_count
            delta_revenue = total_revenue - prev_inv["total_amt"].sum()
            delta_aiv = avg_invoice_value - prev_inv["total_amt"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Invoices", f"{total_invoices:,}", delta=fmt_delta(delta_invoices))
    c2.metric("Total Revenue", f"${total_revenue:,.0f}", delta=fmt_delta(delta_revenue, prefix="$"))
    c3.metric("Customers", f"{unique_customers:,}")
    c4.metric("Products", f"{distinct_products:,}")

    st.metric("Avg Invoice Value", f"${avg_invoice_value:,.2f}", delta=fmt_delta(delta_aiv, prefix="$", decimals=2))
    if start_ts is not None and end_ts is not None:
        st.caption("Deltas compare the selected date range to the immediately preceding period of equal length.")

    st.divider()
    st.subheader("📋 PO extraction data quality")
    st.caption(
        "Only covers the subset of orders with a formal PO document — not the metrics above."
    )
    needs_review = int(f_po["math_check_failed"].sum())
    extraction_errors = int(po_df["error"].notna().sum())
    dq1, dq2 = st.columns(2)
    dq1.metric("⚠️ Needs Review (math check)", f"{needs_review:,}")
    dq2.metric("❌ Extraction Errors", f"{extraction_errors:,}")
    if needs_review or extraction_errors:
        st.caption("See the **Revisions & Data Quality** tab for details on flagged orders.")

    st.divider()
    st.subheader("📈 Annual comparison")
    current_year = str(pd.Timestamp.now().year)
    st.caption(
        f"{current_year} vs. each prior year, by calendar month — {current_year} is bold, "
        "past years are muted for reference. Respects the sidebar filters above."
    )
    ac1, ac2 = st.columns(2)
    with ac1:
        st.caption("Revenue")
        fig_rev_yoy = yoy_annual_chart(f_inv, "effective_date", "total_amt", "sum", "Revenue ($)", palette, current_year)
        if fig_rev_yoy is not None:
            st.plotly_chart(style(fig_rev_yoy, palette), use_container_width=True, key="chart_overview_revenue_yoy")
        else:
            st.caption("Not enough dated invoices in the current filter.")
    with ac2:
        st.caption("Invoices")
        fig_inv_yoy = yoy_annual_chart(f_inv, "effective_date", "id", "nunique", "Invoices", palette, current_year)
        if fig_inv_yoy is not None:
            st.plotly_chart(style(fig_inv_yoy, palette), use_container_width=True, key="chart_overview_orders_yoy")
        else:
            st.caption("Not enough dated invoices in the current filter.")

    st.divider()
    st.subheader("Export")
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        pd.DataFrame({
            "Metric": ["Invoices", "Total Revenue", "Customers", "Products", "Avg Invoice Value",
                       "Needs Review (math check, PO subset)", "Extraction Errors (PO subset)"],
            "Value": [total_invoices, total_revenue, unique_customers, distinct_products,
                      avg_invoice_value, needs_review, extraction_errors],
        }).to_excel(writer, sheet_name="Overview", index=False)
        strip_tz(f_inv.drop(columns=["private_note"], errors="ignore")).to_excel(writer, sheet_name="Invoices", index=False)
        strip_tz(f_inv_items).to_excel(writer, sheet_name="Invoice Line Items", index=False)
        by_product_inv.to_excel(writer, sheet_name="Products", index=False)
        by_customer_inv.to_excel(writer, sheet_name="Customers", index=False)
        strip_tz(f_po.drop(columns=["po_key"], errors="ignore")).to_excel(writer, sheet_name="POs", index=False)
        strip_tz(f_items).to_excel(writer, sheet_name="PO Line Items", index=False)
    st.download_button(
        "📊 Export full report (Excel)",
        excel_buf.getvalue(),
        file_name="gpc_po_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_excel",
    )
    st.caption("Reflects the filters currently applied in the sidebar.")

# ── Reports: Trends ──────────────────────────────────────────────────────────────

with r_trends:
    monthly = f_inv.dropna(subset=["effective_date"]).copy()
    monthly["month"] = monthly["effective_date"].dt.to_period("M").dt.to_timestamp()
    by_month = monthly.groupby("month").agg(orders=("id", "nunique"), revenue=("total_amt", "sum")).reset_index()
    by_month = by_month.sort_values("month")

    if by_month.empty:
        st.info("Not enough dated invoices in the current filter to show trends.")
    else:
        by_month["rolling_avg"] = by_month["orders"].rolling(3, min_periods=1).mean().shift(1)
        by_month["is_spike"] = by_month["orders"] > (by_month["rolling_avg"].fillna(0) * 1.5)
        by_month["spike_label"] = by_month["is_spike"].map({True: "Spike", False: "Normal"})

        st.subheader("Invoices per month")
        fig = px.bar(
            by_month, x="month", y="orders", color="spike_label",
            color_discrete_map={"Normal": palette["categorical"][0], "Spike": palette["status"]["warning"]},
            labels={"month": "", "orders": "Invoices", "spike_label": ""},
        )
        st.plotly_chart(style(fig, palette), use_container_width=True, key="chart_orders_per_month")
        st.caption("🟠 **Spike** = invoice count more than 1.5× the trailing 3-month average.")

        st.subheader("Revenue per month")
        fig2 = px.line(by_month, x="month", y="revenue", labels={"month": "", "revenue": "Revenue ($)"})
        fig2.update_traces(line_color=palette["categorical"][0], line_width=2)
        st.plotly_chart(style(fig2, palette), use_container_width=True, key="chart_revenue_per_month")

        st.subheader("Year-over-year comparison")
        yoy_src = f_inv.dropna(subset=["effective_date"]).copy()
        yoy_src["year"] = yoy_src["effective_date"].dt.year.astype(str)
        yoy_src["moy"] = yoy_src["effective_date"].dt.month
        yoy = yoy_src.groupby(["year", "moy"]).agg(revenue=("total_amt", "sum")).reset_index()
        if yoy["year"].nunique() < 2:
            st.caption("Need orders spanning at least two calendar years in the current filter to compare.")
        else:
            year_colors = color_map_for(yoy["year"].unique().tolist(), palette)
            fig3 = px.line(
                yoy, x="moy", y="revenue", color="year", markers=True,
                color_discrete_map=year_colors,
                labels={"moy": "Month", "revenue": "Revenue ($)", "year": "Year"},
            )
            fig3.update_xaxes(
                tickmode="array", tickvals=list(range(1, 13)),
                ticktext=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            )
            st.plotly_chart(style(fig3, palette), use_container_width=True, key="chart_yoy")

        st.caption(
            "For a detailed requested-vs-delivered trend (day/week/month, per-customer lines), "
            "see **Requested vs Delivered** under **📦 PO Fulfillment**."
        )

# ── Reports: Products ────────────────────────────────────────────────────────────

with r_products:
    if f_inv_items.empty:
        st.info("No line items in the current filter.")
    else:
        st.subheader("Revenue by product")
        fig = px.bar(
            by_product_inv.sort_values("revenue", ascending=True), x="revenue", y="product_name", orientation="h",
            color="product_name", color_discrete_map=product_colors,
            labels={"revenue": "Revenue ($)", "product_name": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, palette), use_container_width=True, key="chart_revenue_by_product")
        st.download_button(
            "⬇️ Download product revenue (CSV)",
            by_product_inv.rename(columns={"product_name": "Product", "revenue": "Revenue ($)", "quantity": "Quantity"})
            .to_csv(index=False).encode("utf-8"),
            file_name="revenue_by_product.csv", mime="text/csv", key="dl_products",
        )

        st.subheader("Product mix over time (quantity)")
        by_month_product = f_inv_items.dropna(subset=["effective_date"]).copy()
        by_month_product["month"] = by_month_product["effective_date"].dt.to_period("M").dt.to_timestamp()
        mix = by_month_product.groupby(["month", "product_name"])["quantity"].sum().reset_index()
        if mix.empty:
            st.info("Not enough dated line items to show product mix over time.")
        else:
            fig3 = px.bar(
                mix, x="month", y="quantity", color="product_name",
                color_discrete_map=product_colors,
                labels={"month": "", "quantity": "Quantity", "product_name": "Product"},
            )
            st.plotly_chart(style(fig3, palette), use_container_width=True, key="chart_product_mix_time")

        st.subheader("Top movers (month over month)")
        movers = month_over_month_movers(f_inv_items, "effective_date", "product_name", "line_total")
        if movers is None:
            st.caption("Need at least two distinct months of data in the current filter to compare.")
        else:
            mdf, curr_m, prev_m = movers
            st.caption(f"Comparing **{curr_m}** to **{prev_m}**.")
            st.dataframe(
                mdf[["product_name", "prev", "curr", "Change"]].rename(columns={
                    "product_name": "Product", "prev": f"{prev_m} Revenue ($)", "curr": f"{curr_m} Revenue ($)",
                }),
                use_container_width=True, hide_index=True,
            )

# ── Reports: Customers ───────────────────────────────────────────────────────────

with r_customers:
    if f_inv.empty:
        st.info("No invoices in the current filter.")
    else:
        st.subheader("Top customers by revenue")
        top = by_customer_inv.sort_values("revenue", ascending=False).head(15).sort_values("revenue")
        fig = px.bar(
            top, x="revenue", y="customer_name", orientation="h",
            labels={"revenue": "Revenue ($)", "customer_name": ""},
        )
        fig.update_traces(marker_color=palette["sequential_blue"][4])
        st.plotly_chart(style(fig, palette), use_container_width=True, key="chart_top_customers")

        cust_month = f_inv.dropna(subset=["effective_date"]).copy()
        cust_month["month"] = cust_month["effective_date"].dt.to_period("M").dt.to_timestamp()

        st.subheader("Customer revenue over time")
        rev_over_time = cust_month.groupby(["month", "customer_name"], as_index=False)["total_amt"].sum()
        if rev_over_time.empty:
            st.caption("Not enough dated invoices in the current filter to show revenue over time.")
        else:
            fig_rev_time = px.line(
                rev_over_time, x="month", y="total_amt", color="customer_name", markers=True,
                color_discrete_map=color_map_for(rev_over_time["customer_name"].dropna().unique().tolist(), palette),
                labels={"month": "", "total_amt": "Revenue ($)", "customer_name": "Customer"},
            )
            st.plotly_chart(style(fig_rev_time, palette), use_container_width=True, key="chart_customer_revenue_time")

        st.subheader("Customer invoices over time")
        orders_over_time = cust_month.groupby(["month", "customer_name"], as_index=False)["id"].nunique()
        orders_over_time = orders_over_time.rename(columns={"id": "invoices"})
        if orders_over_time.empty:
            st.caption("Not enough dated invoices in the current filter to show invoice count over time.")
        else:
            fig_orders_time = px.line(
                orders_over_time, x="month", y="invoices", color="customer_name", markers=True,
                color_discrete_map=color_map_for(orders_over_time["customer_name"].dropna().unique().tolist(), palette),
                labels={"month": "", "invoices": "Invoices", "customer_name": "Customer"},
            )
            st.plotly_chart(style(fig_orders_time, palette), use_container_width=True, key="chart_customer_orders_time")

        st.subheader("Product mix over time, by customer")
        st.caption("Pick a customer to see what they've bought, by product, over time.")
        cust_options = sorted(inv_items_all["customer_name"].dropna().unique())
        if not cust_options:
            st.caption("No customers with line items in the data yet.")
        else:
            picked_customer = st.selectbox("Customer", cust_options, key="customer_product_trend_pick")
            cust_items = f_inv_items[f_inv_items["customer_name"] == picked_customer].dropna(subset=["effective_date"]).copy()
            cust_items["month"] = cust_items["effective_date"].dt.to_period("M").dt.to_timestamp()
            cust_mix = cust_items.groupby(["month", "product_name"], as_index=False)["quantity"].sum()
            if cust_mix.empty:
                st.caption(f"No dated line items for {picked_customer} in the current filter.")
            else:
                fig_cust_mix = px.bar(
                    cust_mix, x="month", y="quantity", color="product_name",
                    color_discrete_map=product_colors,
                    labels={"month": "", "quantity": "Quantity", "product_name": "Product"},
                )
                st.plotly_chart(style(fig_cust_mix, palette), use_container_width=True, key="chart_customer_product_mix_time")

        st.subheader("Customer summary")
        customer_table = by_customer_inv.sort_values("revenue", ascending=False).rename(columns={
            "customer_name": "Customer", "invoices": "Invoices",
            "revenue": "Revenue ($)", "avg_invoice_value": "Avg Invoice ($)",
        })
        st.dataframe(customer_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download customer summary (CSV)",
            customer_table.to_csv(index=False).encode("utf-8"),
            file_name="customer_summary.csv", mime="text/csv", key="dl_customers",
        )

        st.subheader("Top movers (month over month)")
        movers = month_over_month_movers(f_inv, "effective_date", "customer_name", "total_amt")
        if movers is None:
            st.caption("Need at least two distinct months of data in the current filter to compare.")
        else:
            mdf, curr_m, prev_m = movers
            st.caption(f"Comparing **{curr_m}** to **{prev_m}**.")
            st.dataframe(
                mdf[["customer_name", "prev", "curr", "Change"]].rename(columns={
                    "customer_name": "Customer", "prev": f"{prev_m} Revenue ($)", "curr": f"{curr_m} Revenue ($)",
                }),
                use_container_width=True, hide_index=True,
            )

# ── PO Fulfillment: Requested vs Delivered ────────────────────────────────────────

with pf_rvd:
    st.caption(
        "Compares PO line items (requested) to matched QuickBooks invoice line items "
        "(delivered), respecting the sidebar filters above. Confirm matches in the "
        "🔗 Match tab first — this report only reflects confirmed links."
    )

    # Controls are always rendered (not gated on po_ids) — the sidebar date range is
    # now based on the wider invoice timeline (see the QBO-invoices-as-primary-source
    # rework), so a narrow preset can easily fall entirely outside the PO date range;
    # gating these widgets on po_ids made them vanish across reruns in exactly that
    # case (the same class of bug fixed for the Pricing tab's product/size pickers).
    st.subheader("Detailed breakdown: requested vs. delivered")
    st.caption("Complete detail — slice by time period, customer, product, and size, in any combination.")
    bc1, bc2 = st.columns(2)
    period_choice = bc1.selectbox(
        "Time period", ["All time", "Day", "Week", "Month", "Quarter", "Year"], index=3, key="breakdown_period",
    )
    dims = bc2.multiselect(
        "Break down by", ["Customer", "Product", "Size"], default=["Product"], key="breakdown_dims",
    )

    po_ids = f_po["id"].tolist()
    if not po_ids:
        st.info("No orders in the current filter.")
    else:
        matched_items = load_matched_line_items()
        detail = matched_items[matched_items["po_id"].isin(po_ids)].copy()

        if detail.empty:
            st.info("No confirmed matches with line-item detail in the current filter.")
        else:
            period_freq = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}
            group_cols = []
            if period_choice != "All time":
                detail["Period"] = detail["effective_date"].dt.to_period(period_freq[period_choice]).dt.start_time
                group_cols.append("Period")
            dim_col_map = {"Customer": "customer_name", "Product": "product_name", "Size": "container_size"}
            group_cols += [dim_col_map[d] for d in dims]

            if not group_cols:
                detail["All"] = "All"
                group_cols = ["All"]

            grouped = detail.groupby(group_cols, as_index=False).agg(
                requested_qty=("requested_qty", "sum"), requested_amount=("requested_amount", "sum"),
                delivered_qty=("delivered_qty", "sum"), delivered_amount=("delivered_amount", "sum"),
                po_math_notes=("po_math_note", lambda s: "; ".join(sorted(set(x for x in s if isinstance(x, str) and x)))[:200]),
            )
            grouped["Qty Variance"] = grouped["delivered_qty"] - grouped["requested_qty"]
            grouped["$ Variance"] = grouped["delivered_amount"] - grouped["requested_amount"]
            grouped["Fulfillment %"] = grouped.apply(
                lambda r: round(r["delivered_amount"] / r["requested_amount"] * 100, 1)
                if r["requested_amount"] else None,
                axis=1,
            )
            grouped = grouped.sort_values(
                ["Period"] + [c for c in group_cols if c != "Period"] if "Period" in group_cols else "$ Variance"
            )

            display_df = grouped.rename(columns={
                "customer_name": "Customer", "product_name": "Product", "container_size": "Size",
                "requested_qty": "Requested Qty", "requested_amount": "Requested ($)",
                "delivered_qty": "Delivered Qty", "delivered_amount": "Delivered ($)",
                "po_math_notes": "PO Math Note",
            })
            if "All" in display_df.columns:
                display_df = display_df.drop(columns=["All"])

            st.dataframe(display_df, use_container_width=True, hide_index=True)
            st.caption(
                "**PO Math Note** flags a known arithmetic quirk on the PO side (e.g. a "
                "per-unit surcharge baked into the printed total) — a $ Variance next to a "
                "note is a documented pricing quirk, not necessarily a fulfillment shortfall."
            )
            st.download_button(
                "⬇️ Download breakdown (CSV)",
                display_df.to_csv(index=False).encode("utf-8"),
                file_name="requested_vs_delivered_breakdown.csv", mime="text/csv", key="dl_breakdown",
            )

            if period_choice != "All time":
                show_by_customer = "Customer" in dims
                trend_group_cols = ["Period"] + (["customer_name"] if show_by_customer else [])

                st.subheader("📈 Requested vs. delivered trend")
                chart_src = detail.groupby(trend_group_cols, as_index=False).agg(
                    requested_amount=("requested_amount", "sum"), delivered_amount=("delivered_amount", "sum"),
                )
                chart_long = chart_src.melt(
                    id_vars=trend_group_cols, value_vars=["requested_amount", "delivered_amount"],
                    var_name="Type", value_name="Amount",
                )
                chart_long["Type"] = chart_long["Type"].map({
                    "requested_amount": "Requested", "delivered_amount": "Delivered",
                })
                if show_by_customer:
                    cust_colors = color_map_for(chart_long["customer_name"].dropna().unique().tolist(), palette)
                    fig_bd = px.line(
                        chart_long, x="Period", y="Amount", color="customer_name", line_dash="Type",
                        color_discrete_map=cust_colors, markers=True,
                        labels={"Period": "", "Amount": "Revenue ($)", "customer_name": "Customer"},
                    )
                else:
                    fig_bd = px.line(
                        chart_long, x="Period", y="Amount", color="Type", markers=True,
                        color_discrete_map={"Requested": palette["categorical"][0], "Delivered": palette["categorical"][1]},
                        labels={"Period": "", "Amount": "Revenue ($)"},
                    )
                st.plotly_chart(style(fig_bd, palette), use_container_width=True, key="chart_breakdown_period")
                st.caption(
                    "Chart aggregates across product/size even when selected above — see the table for "
                    "the full multi-dimensional detail."
                    + (" One line per customer; dashed = Delivered, solid = Requested." if show_by_customer else "")
                )

                st.subheader("📅 Ordering trends")
                st.caption(
                    "Number of purchase orders placed per period, per the sidebar filters — reflects "
                    "every order in the filter, not just ones with a confirmed QuickBooks match."
                )
                order_src = f_po.dropna(subset=["effective_date"]).copy()
                order_src["Period"] = order_src["effective_date"].dt.to_period(period_freq[period_choice]).dt.start_time
                order_group_cols = ["Period"] + (["customer_name"] if show_by_customer else [])
                order_counts = (
                    order_src.groupby(order_group_cols, as_index=False)["id"].nunique()
                    .rename(columns={"id": "Orders"})
                )
                if show_by_customer:
                    fig_orders = px.line(
                        order_counts, x="Period", y="Orders", color="customer_name", markers=True,
                        color_discrete_map=color_map_for(order_counts["customer_name"].dropna().unique().tolist(), palette),
                        labels={"Period": "", "customer_name": "Customer"},
                    )
                else:
                    fig_orders = px.line(order_counts, x="Period", y="Orders", markers=True, labels={"Period": ""})
                    fig_orders.update_traces(line_color=palette["categorical"][0])
                st.plotly_chart(style(fig_orders, palette), use_container_width=True, key="chart_order_trend")

        st.subheader("Matched PO ↔ Invoice detail")
        rvd_conn = psycopg2.connect(get_database_url())
        try:
            with rvd_conn.cursor() as cur:
                cur.execute(
                    "SELECT po.po_number, po.source_file, po.customer_name, po.total, "
                    "inv.doc_number, inv.txn_date, inv.total_amt, l.match_method "
                    "FROM po_invoice_links l "
                    "JOIN purchase_orders po ON po.id = l.po_id "
                    "JOIN qbo_invoices inv ON inv.id = l.invoice_id "
                    "WHERE l.confirmed = TRUE AND l.po_id = ANY(%s) "
                    "ORDER BY po.po_number",
                    (po_ids,),
                )
                cols = [d[0] for d in cur.description]
                detail_rows = cur.fetchall()
        finally:
            rvd_conn.close()
        if not detail_rows:
            st.caption("No confirmed matches in the current filter yet.")
        else:
            detail_df = pd.DataFrame(detail_rows, columns=cols)
            detail_df["variance"] = detail_df["total_amt"].astype(float) - detail_df["total"].astype(float)
            st.dataframe(
                detail_df.rename(columns={
                    "po_number": "PO Number", "source_file": "Source File", "customer_name": "Customer",
                    "total": "PO Total ($)", "doc_number": "Invoice #", "txn_date": "Invoice Date",
                    "total_amt": "Invoice Total ($)", "match_method": "Match Method", "variance": "Variance ($)",
                }),
                use_container_width=True, hide_index=True,
            )

        st.subheader("🚚 Delivery & donation charges by customer")
        st.caption(
            "QuickBooks Delivery/Donation line items, attributed to whichever PO their "
            "containing invoice is confirmed-linked to. Only invoices confirmed-linked "
            "in the current filter appear here."
        )
        dd_conn = psycopg2.connect(get_database_url())
        try:
            dd_rows = pd.read_sql_query(
                "SELECT po.customer_name, po.po_number, po.source_file, ii.category, "
                "SUM(ii.line_total) AS total, COUNT(*) AS n_lines "
                "FROM po_invoice_links l "
                "JOIN purchase_orders po ON po.id = l.po_id "
                "JOIN qbo_invoice_items ii ON ii.invoice_id = l.invoice_id "
                "WHERE l.confirmed = TRUE AND l.po_id = ANY(%(ids)s) "
                "AND ii.category IN ('delivery', 'donation') "
                "GROUP BY po.customer_name, po.po_number, po.source_file, ii.category "
                "ORDER BY po.customer_name, po.po_number",
                dd_conn, params={"ids": po_ids},
            )
        finally:
            dd_conn.close()

        if dd_rows.empty:
            st.caption("No delivery or donation charges on confirmed-linked invoices in the current filter.")
        else:
            st.dataframe(
                dd_rows.rename(columns={
                    "customer_name": "Customer", "po_number": "PO Number", "source_file": "Source File",
                    "category": "Type", "total": "Total ($)", "n_lines": "# Lines",
                }),
                use_container_width=True, hide_index=True,
            )
            st.download_button(
                "⬇️ Download delivery & donation charges (CSV)",
                dd_rows.to_csv(index=False).encode("utf-8"),
                file_name="delivery_donation_by_po.csv", mime="text/csv", key="dl_delivery_donation",
            )

# ── Reports: Pricing ─────────────────────────────────────────────────────────────

with r_pricing:
    st.caption(
        "Unit price paid over time per customer, for a selected product/size — see the "
        "pre/post-2024-06-01 pricing standardization and any ongoing drift. Respects the "
        "sidebar filters above."
    )
    # Product/size options come from ALL priced history (not the sidebar date filter),
    # so the selectors stay stable across filter changes — only the plotted series below
    # is scoped to the current filter. Keeps the widgets' `key`-bound state valid across
    # reruns instead of the option list shrinking out from under a prior selection.
    priced_all = all_items[
        (~all_items["is_sample"].fillna(False)) & all_items["unit_price"].notna()
        & (all_items["product_name"] != "UNKNOWN")
    ]

    if priced_all.empty:
        st.info("No priced line items in the data yet.")
    else:
        pc1, pc2 = st.columns(2)
        products = sorted(priced_all["product_name"].dropna().unique())
        prod_choice = pc1.selectbox("Product", products, key="pricing_product")
        sizes = sorted(priced_all.loc[priced_all["product_name"] == prod_choice, "container_size"].dropna().unique())
        size_choice = pc2.selectbox("Size", sizes, key="pricing_size")

        series = priced_all[
            priced_all["po_id"].isin(f_po["id"])
            & (priced_all["product_name"] == prod_choice) & (priced_all["container_size"] == size_choice)
        ].sort_values("effective_date")

        if series.empty:
            st.info("No priced history for this product/size in the current filter.")
        else:
            cust_colors = color_map_for(series["customer_name"].dropna().unique().tolist(), palette)
            fig_price = px.scatter(
                series, x="effective_date", y="unit_price", color="customer_name",
                color_discrete_map=cust_colors,
                labels={"effective_date": "", "unit_price": "Unit Price ($)", "customer_name": "Customer"},
            )
            fig_price.update_traces(mode="lines+markers")
            fig_price.add_shape(
                type="line", x0="2024-06-01", x1="2024-06-01", y0=0, y1=1, yref="paper",
                line=dict(dash="dash", color=palette["ink_muted"]),
            )
            fig_price.add_annotation(
                x="2024-06-01", y=1, yref="paper", showarrow=False, yanchor="bottom",
                text="Pricing standardized", font=dict(color=palette["ink_muted"], size=10),
            )
            st.plotly_chart(style(fig_price, palette), use_container_width=True, key="chart_pricing_history")

            ref_prices_df = load_reference_prices()
            ref_for_selection = ref_prices_df[
                (ref_prices_df["product_name"] == prod_choice) & (ref_prices_df["container_size"] == size_choice)
            ]
            if not ref_for_selection.empty:
                st.caption("Current reference price for this product/size, per customer:")
                st.dataframe(
                    ref_for_selection[["customer_name", "price", "source"]].rename(columns={
                        "customer_name": "Customer", "price": "Reference Price ($)", "source": "Source",
                    }),
                    use_container_width=True, hide_index=True,
                )
            st.caption("Manage/override reference prices in the 🏷️ Reference Prices tab.")

# ── PO Fulfillment: Revisions & Data Quality ──────────────────────────────────────

with pf_revisions:
    st.caption("Respects the sidebar filters above, except **Extraction errors** (errored files often have no usable date).")

    st.subheader("Orders with revisions")
    rev_po = f_po[f_po["is_revision"]]
    if rev_po.empty:
        st.caption("No revisions found in the current data.")
    else:
        rev_table = rev_po[["po_number", "version_label", "effective_date", "customer_name", "total", "source_file"]].rename(columns={
            "po_number": "PO Number", "version_label": "Version", "effective_date": "Date",
            "customer_name": "Customer", "total": "Total ($)", "source_file": "Source File",
        })
        st.dataframe(rev_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download revisions (CSV)", rev_table.to_csv(index=False).encode("utf-8"),
            file_name="revisions.csv", mime="text/csv", key="dl_revisions",
        )

    st.subheader("📦 Order lead time")
    lead = f_po.dropna(subset=["effective_date", "delivery_date"]).copy()
    lead["lead_days"] = (lead["delivery_date"] - lead["effective_date"]).dt.days
    lead = lead[lead["lead_days"] >= 0]
    if lead.empty:
        st.caption("Not enough orders with both an order date and a delivery date in the current filter.")
    else:
        lc1, lc2 = st.columns(2)
        lc1.metric("Median Lead Time", f"{lead['lead_days'].median():.0f} days")
        lc2.metric("Average Lead Time", f"{lead['lead_days'].mean():.1f} days")
        fig_lead = px.histogram(lead, x="lead_days", nbins=20, labels={"lead_days": "Lead time (days)"})
        fig_lead.update_traces(marker_color=palette["sequential_blue"][3])
        st.plotly_chart(style(fig_lead, palette), use_container_width=True, key="chart_lead_time")

    st.subheader("🔁 Revision impact")
    st.caption("Compares each order's original total to its latest revision's total.")
    hist_po = valid_po[valid_po["po_key"].isin(f_po["po_key"])].sort_values(["po_key", "effective_date", "id"])
    impacts = []
    for po_key, grp in hist_po.groupby("po_key"):
        if len(grp) < 2:
            continue
        original_total, final_total = grp.iloc[0]["total"], grp.iloc[-1]["total"]
        if pd.notna(original_total) and pd.notna(final_total):
            impacts.append(final_total - original_total)
    if impacts:
        impacts = pd.Series(impacts)
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Revisions increasing value", int((impacts > 0).sum()))
        ic2.metric("Revisions decreasing value", int((impacts < 0).sum()))
        ic3.metric("Net $ impact from revisions", f"${impacts.sum():,.2f}")
    else:
        st.caption("No multi-version orders in the current filter.")

    st.subheader("📝 What changed in the latest revision")
    diff_items = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["revision_status"].isin(["Added", "Changed", "Removed"])
    ]
    if diff_items.empty:
        st.caption("No line-item changes in the latest revision of any order in the current filter.")
    else:
        st.dataframe(
            diff_items[["po_number", "customer_name", "product_name", "revision_status", "changes"]].rename(columns={
                "po_number": "PO Number", "customer_name": "Customer", "product_name": "Product",
                "revision_status": "Status", "changes": "Changes",
            }),
            use_container_width=True, hide_index=True,
        )

    st.subheader("⚠️ Math check failures")
    math_fail = f_po[f_po["math_check_failed"]]
    if math_fail.empty:
        st.caption("None — arithmetic on every order checks out.")
    else:
        math_table = math_fail[["po_number", "source_file", "customer_name", "math_check_detail"]].rename(columns={
            "po_number": "PO Number", "source_file": "Source File",
            "customer_name": "Customer", "math_check_detail": "Issue",
        })
        st.dataframe(math_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download math check failures (CSV)", math_table.to_csv(index=False).encode("utf-8"),
            file_name="math_check_failures.csv", mime="text/csv", key="dl_math_fail",
        )

    st.subheader("💲 Price anomalies")
    st.caption(
        "Line items whose unit price deviates more than 10% from the reference price for "
        "that customer/product/size. See 🏷️ Reference Prices (under 📊 Reports) to review or override."
    )
    price_issues = all_items[all_items["po_id"].isin(f_po["id"]) & all_items["price_anomaly"].notna()]
    if price_issues.empty:
        st.caption("None — every price is within range of its reference.")
    else:
        price_table = price_issues[
            ["po_number", "customer_name", "product_name", "container_size", "price_anomaly"]
        ].rename(columns={
            "po_number": "PO Number", "customer_name": "Customer", "product_name": "Product",
            "container_size": "Size", "price_anomaly": "Issue",
        })
        st.dataframe(price_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download price anomalies (CSV)", price_table.to_csv(index=False).encode("utf-8"),
            file_name="price_anomalies.csv", mime="text/csv", key="dl_price_anomalies",
        )

    st.subheader("❌ Extraction errors")
    errored = po_df[po_df["error"].notna()]
    if errored.empty:
        st.caption("None — every file extracted successfully.")
    else:
        err_table = errored[["source_file", "error"]].rename(columns={"source_file": "Source File", "error": "Error"})
        st.dataframe(err_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download extraction errors (CSV)", err_table.to_csv(index=False).encode("utf-8"),
            file_name="extraction_errors.csv", mime="text/csv", key="dl_errors",
        )

# ── Data Management: Raw Data ─────────────────────────────────────────────────────

with dm_raw:
    st.caption("Filtered line items — current version of each PO, per the sidebar filters.")
    display_cols = [
        "po_number", "effective_date", "customer_name", "product_name", "container_size",
        "quantity", "unit_price", "line_total", "is_sample", "needs_review", "math_mismatch",
    ]
    table = f_items[display_cols].rename(columns={
        "po_number": "PO Number", "effective_date": "Date", "customer_name": "Customer",
        "product_name": "Product", "container_size": "Size", "quantity": "Qty",
        "unit_price": "Unit Price ($)", "line_total": "Line Total ($)",
        "is_sample": "Sample", "needs_review": "Review", "math_mismatch": "Math Check",
    })
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download as CSV",
        table.to_csv(index=False).encode("utf-8"),
        file_name="po_line_items.csv",
        mime="text/csv",
        key="dl_raw",
    )

# ── Data Management: Edit ─────────────────────────────────────────────────────────

with dm_edit:
    st.caption(
        "Edits are permanent — once saved, that PO stops receiving updates from future "
        "extraction syncs (its header and line items are frozen as you leave them here)."
    )

    picker = latest_po.sort_values("po_number", na_position="last")
    label_to_id = {
        f"{row.po_number or row.source_file} — {row.customer_name or 'Unknown customer'}": int(row.id)
        for row in picker.itertuples()
    }
    selected_label = st.selectbox("Select a PO to edit", options=list(label_to_id.keys()))
    selected_id = label_to_id.get(selected_label)

    if selected_id is not None:
        row = latest_po[latest_po["id"] == selected_id].iloc[0]
        if bool(row.get("edited")):
            st.info(f"This record was already manually edited (at {row.get('edited_at')}).")

        with st.form(f"edit_form_{selected_id}"):
            c1, c2 = st.columns(2)
            po_number = c1.text_input("PO Number", value=row["po_number"] or "", key=f"po_number_{selected_id}")
            customer_name = c2.text_input("Customer", value=row["customer_name"] or "", key=f"customer_{selected_id}")
            po_date = c1.date_input(
                "PO Date", value=row["po_date"].date() if pd.notna(row["po_date"]) else None, key=f"po_date_{selected_id}",
            )
            delivery_date = c2.date_input(
                "Delivery Date", value=row["delivery_date"].date() if pd.notna(row["delivery_date"]) else None,
                key=f"delivery_date_{selected_id}",
            )
            subtotal = c1.number_input(
                "Subtotal ($)", value=float(row["subtotal"]) if pd.notna(row["subtotal"]) else 0.0,
                step=0.01, format="%.2f", key=f"subtotal_{selected_id}",
            )
            tax = c2.number_input(
                "Tax ($)", value=float(row["tax"]) if pd.notna(row["tax"]) else 0.0,
                step=0.01, format="%.2f", key=f"tax_{selected_id}",
            )
            total = c1.number_input(
                "Total ($)", value=float(row["total"]) if pd.notna(row["total"]) else 0.0,
                step=0.01, format="%.2f", key=f"total_{selected_id}",
            )
            notes = st.text_area("Notes", value=row["notes"] or "", key=f"notes_{selected_id}")

            st.markdown("**Line items**")
            items_seed = all_items[all_items["po_id"] == selected_id][
                ["product_name", "container_size", "quantity", "unit_price", "line_total", "is_sample"]
            ].reset_index(drop=True)
            edited_items = st.data_editor(
                items_seed, num_rows="dynamic", use_container_width=True, key=f"items_editor_{selected_id}",
                column_config={
                    "quantity": st.column_config.NumberColumn("Qty"),
                    "unit_price": st.column_config.NumberColumn("Unit Price ($)", format="%.2f"),
                    "line_total": st.column_config.NumberColumn("Line Total ($)", format="%.2f"),
                    "is_sample": st.column_config.CheckboxColumn("Sample"),
                },
            )

            submitted = st.form_submit_button("💾 Save changes")

        if submitted:
            items = [
                item for item in edited_items.to_dict("records")
                if item.get("product_name")  # drop blank rows added via the "+" control
            ]
            header = {
                "po_number": po_number or None,
                "customer_name": customer_name or None,
                "po_date": po_date,
                "delivery_date": delivery_date,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "notes": notes or None,
            }
            save_po_edit(selected_id, header, items)
            load_data.clear()
            st.success("Saved.")
            st.rerun()

# ── Reports: Reference Prices ─────────────────────────────────────────────────────

with r_ref_prices:
    st.caption(
        "Expected/current price per customer, product, and size — the basis for the "
        "💲 Price anomalies flag in Revisions & Data Quality. **auto** rows refresh "
        "automatically from the most recent price actually paid each time new POs are "
        "extracted; edit a price or add a row below to set a permanent manual override — "
        "overrides are never touched by future refreshes."
    )
    ref_df = load_reference_prices()
    editor_seed = ref_df[["customer_name", "product_name", "container_size", "price", "source"]].copy()
    edited_prices = st.data_editor(
        editor_seed, num_rows="dynamic", use_container_width=True, key="reference_prices_editor",
        column_config={
            "customer_name": st.column_config.TextColumn("Customer"),
            "product_name": st.column_config.TextColumn("Product"),
            "container_size": st.column_config.TextColumn("Size"),
            "price": st.column_config.NumberColumn("Price ($)", format="%.2f"),
            "source": st.column_config.TextColumn("Source", disabled=True),
        },
    )

    if st.button("💾 Save changes", key="save_reference_prices"):
        seed_key_price = {
            (r["customer_name"], r["product_name"], r["container_size"]): r["price"]
            for r in editor_seed.to_dict("records")
        }
        rows = []
        for r in edited_prices.to_dict("records"):
            cust, prod, size, price = r.get("customer_name"), r.get("product_name"), r.get("container_size"), r.get("price")
            if not (cust and prod and size) or price is None:
                continue
            key = (cust, prod, size)
            if key in seed_key_price and float(seed_key_price[key]) == float(price):
                continue  # unchanged — leave alone so it can still auto-refresh later
            rows.append({"customer_name": cust, "product_name": prod, "container_size": size, "price": price})
        if rows:
            save_reference_prices(rows)
            load_reference_prices.clear()
            st.success(f"Saved {len(rows)} changed/added reference price(s).")
            st.rerun()
        else:
            st.info("No changes to save.")

# ── QuickBooks ───────────────────────────────────────────────────────────────────

with tab_qbo:
    st.caption(
        "Phase 1: connect to QuickBooks and pull raw invoice data — the matching logic "
        "against PO requests comes in a follow-up phase, once we've seen what fields "
        "this company's invoices actually populate."
    )
    if qbo_client.is_production():
        st.warning("⚠️ Environment: **Production** — this pulls real invoice data.")
    else:
        st.info("Environment: **Sandbox** (test data only). Set `qbo_environment = \"production\"` to switch.")

    _conn = psycopg2.connect(get_database_url())
    try:
        connection = qbo_client.get_connection(_conn)
    finally:
        _conn.close()

    if connection is None:
        st.info("Not connected to QuickBooks yet.")
        oauth_state = st.session_state.setdefault("qbo_oauth_state", secrets.token_urlsafe(16))
        st.link_button("🔗 Connect to QuickBooks", qbo_client.build_authorize_url(oauth_state))
    else:
        st.success(f"Connected — realm ID `{connection['realm_id']}` (since {connection['connected_at']}).")
        if connection.get("last_synced_at"):
            st.caption(f"Last synced: {connection['last_synced_at']} — next sync only pulls invoices changed since then.")
        else:
            st.caption("Never synced yet — the next sync pulls everything.")

        full_resync = st.checkbox("Full resync (ignore last-synced cursor, re-pull everything)")

        c1, c2 = st.columns(2)
        if c1.button("🔄 Sync invoices"):
            sync_conn = psycopg2.connect(get_database_url())
            try:
                with st.spinner("Pulling the product catalog from QuickBooks..."):
                    item_count = qbo_client.sync_items(sync_conn)
                with st.spinner("Pulling invoices from QuickBooks..."):
                    count = qbo_client.sync_invoices(sync_conn, full_resync=full_resync)
                st.success(f"Synced {item_count} catalog item(s) and {count} invoice(s).")
            except Exception as e:
                st.error(f"Sync failed: {e}")
            finally:
                sync_conn.close()
        if c2.button("Disconnect"):
            dc_conn = psycopg2.connect(get_database_url())
            try:
                qbo_client.disconnect(dc_conn)
            finally:
                dc_conn.close()
            st.rerun()

        inv_conn = psycopg2.connect(get_database_url())
        try:
            invoices_df = pd.read_sql_query(
                "SELECT doc_number, customer_name, txn_date, ship_date, due_date, "
                "total_amt, private_note, raw_json FROM qbo_invoices "
                "ORDER BY txn_date DESC NULLS LAST",
                inv_conn,
            )
        finally:
            inv_conn.close()

        if invoices_df.empty:
            st.caption("No invoices synced yet — click Sync invoices above.")
        else:
            st.dataframe(
                invoices_df.drop(columns=["raw_json"]).rename(columns={
                    "doc_number": "Doc #", "customer_name": "Customer", "txn_date": "Invoice Date",
                    "ship_date": "Ship Date", "due_date": "Due Date", "total_amt": "Total ($)",
                    "private_note": "Private Note",
                }),
                use_container_width=True, hide_index=True,
            )
            with st.expander("Inspect one raw invoice (for designing Phase 2's matcher)"):
                idx = st.number_input("Row index", min_value=0, max_value=len(invoices_df) - 1, value=0)
                st.json(invoices_df.iloc[int(idx)]["raw_json"])

        st.divider()
        st.subheader("📦 Item Catalog")
        st.caption(
            "QuickBooks' own Item list — the product master catalog invoice lines are "
            "matched against by ID. Read-only here; re-synced each time you click Sync invoices above."
        )
        cat_conn = psycopg2.connect(get_database_url())
        try:
            items_df = pd.read_sql_query(
                "SELECT name, item_type, active, category, product_name, container_size, "
                "unit_price, sku FROM qbo_items ORDER BY category, name",
                cat_conn,
            )
        finally:
            cat_conn.close()

        if items_df.empty:
            st.caption("No catalog synced yet — click Sync invoices above.")
        else:
            counts = items_df["category"].value_counts()
            cat_cols = st.columns(len(counts))
            for col, (cat, n) in zip(cat_cols, counts.items()):
                col.metric(cat.capitalize(), n)
            st.dataframe(
                items_df.rename(columns={
                    "name": "Name", "item_type": "QBO Type", "active": "Active",
                    "category": "Category", "product_name": "Product", "container_size": "Size",
                    "unit_price": "List Price ($)", "sku": "SKU",
                }),
                use_container_width=True, hide_index=True,
            )

# ── PO Fulfillment: Match ──────────────────────────────────────────────────────────

with pf_match:
    st.caption(
        "Match PO requests to QuickBooks invoices — run automated matching, review its "
        "suggestions, or search and link manually. See the **Requested vs Delivered** "
        "tab alongside this one for the resulting report."
    )

    mc = psycopg2.connect(get_database_url())

    def _items_table(items):
        if not items:
            st.caption("No line items.")
            return
        st.dataframe(
            pd.DataFrame(items).rename(columns={
                "product_name": "Product", "container_size": "Size", "quantity": "Qty",
                "unit_price": "Unit $", "line_total": "Total $", "is_sample": "Sample",
                "category": "Category",
            }),
            use_container_width=True, hide_index=True,
        )

    try:
        mcol1, mcol2 = st.columns(2)
        if mcol1.button("🔄 Run matching"):
            with st.spinner("Matching POs to invoices..."):
                summary = qbo_matcher.run_matching(mc)
            st.success(
                f"{summary['auto_matched']} auto-matched with certainty, "
                f"{summary['customer_mismatch']} PO-number match(es) held for review "
                f"(customer didn't corroborate), "
                f"{summary['fuzzy_candidates']} fuzzy candidate(s) added for review, "
                f"{summary['ambiguous_po_number']} still-ambiguous PO-number match(es), "
                f"{summary['no_candidates']} PO(s) with no candidate at all "
                f"(out of {summary['total_pos']} total POs). "
                f"{summary['voided_released']} PO(s) released back for rematching (their "
                f"invoice was voided in QuickBooks), {summary['voided_pruned']} stale voided "
                f"candidate(s) pruned. "
                f"Fuzzy date window: ±{summary['date_window_days']} days."
            )
        if mcol2.button("📁 Sync Drive links"):
            progress_bar = st.progress(0.0, text="Searching Google Drive...")

            def _drive_progress(i, total):
                progress_bar.progress(i / total, text=f"Searching Google Drive... {i}/{total}")

            try:
                drive_summary = gdrive_client.sync_drive_links(mc, progress=_drive_progress)
                progress_bar.empty()
                msg = (
                    f"{drive_summary['linked']} PO(s) linked to their PDF, "
                    f"{drive_summary['not_found']} not found in this batch "
                    f"(checked {drive_summary['total_checked']})."
                )
                if drive_summary["remaining"]:
                    msg += f" {drive_summary['remaining']} more PO(s) still to check — click again to continue."
                st.success(msg)
            except Exception as e:
                progress_bar.empty()
                st.error(f"Drive sync failed: {e}")
        with mc.cursor() as _cur:
            _cur.execute("SELECT COUNT(*), COUNT(drive_file_id) FROM purchase_orders WHERE error IS NULL")
            _total_po, _linked_po = _cur.fetchone()
        st.caption(f"📁 {_linked_po} of {_total_po} POs linked to their original PDF in Google Drive.")

        st.subheader("Needs review")
        needs_review = qbo_matcher.get_needs_review(mc)
        if not needs_review:
            st.caption("Nothing pending review.")
        else:
            po_items_map, inv_items_map = qbo_matcher.get_line_items_for_review(
                mc, [r["po_id"] for r in needs_review], [r["invoice_id"] for r in needs_review],
            )

            for row in needs_review:
                confidence = qbo_matcher.confidence_label(row["match_method"], row["match_score"])
                summary = (
                    f"PO {row['po_number'] or row['source_file']} ({row['po_customer']}, "
                    f"${row['po_total'] or 0:,.2f}) ↔ Invoice {row['doc_number']} "
                    f"({row['inv_customer']}, {row['txn_date']}, ${row['total_amt'] or 0:,.2f}) "
                    f"— {confidence}"
                )
                with st.expander(summary):
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("**Purchase Order**")
                        st.write(f"PO Number: {row['po_number'] or row['source_file']}")
                        if row.get("drive_file_id"):
                            st.markdown(f"[📄 Open original PDF ↗]({gdrive_client.file_view_url(row['drive_file_id'])})")
                        st.write(f"Customer: {row['po_customer']}")
                        st.write(
                            f"PO Date: {row['po_date'] or '—'} · Sent: {row['sent_date'] or '—'} · "
                            f"Delivery: {row['delivery_date'] or '—'}"
                        )
                        st.write(
                            f"Subtotal: ${row['po_subtotal'] or 0:,.2f} · Tax: ${row['po_tax'] or 0:,.2f} · "
                            f"Total: ${row['po_total'] or 0:,.2f}"
                        )
                        if row.get("po_notes"):
                            st.caption(f"Notes: {row['po_notes']}")
                        _items_table(po_items_map.get(row["po_id"], []))
                    with dc2:
                        st.markdown("**QuickBooks Invoice**")
                        st.write(f"Invoice #: {row['doc_number']}")
                        st.markdown(f"[Open in QuickBooks ↗]({qbo_client.invoice_url(row['qbo_invoice_id'])})")
                        st.write(f"Customer: {row['inv_customer']}")
                        st.write(f"Invoice Date: {row['txn_date'] or '—'} · Due: {row['due_date'] or '—'}")
                        st.write(f"Total: ${row['total_amt'] or 0:,.2f}")
                        if row.get("inv_note"):
                            st.caption(f"Note: {row['inv_note']}")
                        _items_table(inv_items_map.get(row["invoice_id"], []))

                    bc1, bc2 = st.columns(2)
                    if bc1.button("✅ Confirm match", key=f"confirm_{row['po_id']}_{row['invoice_id']}"):
                        qbo_matcher.confirm_link(mc, row["po_id"], row["invoice_id"])
                        st.rerun()
                    if bc2.button("❌ Reject", key=f"reject_{row['po_id']}_{row['invoice_id']}"):
                        qbo_matcher.reject_link(mc, row["po_id"], row["invoice_id"])
                        st.rerun()

        st.divider()
        st.subheader("🔍 Search & match manually")
        unresolved_count = len(qbo_matcher.get_unlinked_pos(mc))
        st.caption(
            "Find and link any PO to any invoice directly — independent of the automated "
            f"suggestions above. {unresolved_count} PO(s) still without a confirmed match."
        )

        wc1, wc2 = st.columns(2)
        selected_po = selected_invoice = None
        po_detail = None

        with wc1:
            st.markdown("**Purchase Order**")
            po_search = st.text_input("Search PO number, customer, or filename", key="workbench_po_search")
            po_include_matched = st.checkbox("Include already-matched POs", key="workbench_po_include_matched")
            po_results = qbo_matcher.search_pos(mc, po_search, limit=50, include_matched=po_include_matched)
            if not po_results:
                st.caption("No matching POs.")
            else:
                po_label_map = {
                    f"{p['po_number'] or p['source_file']} — {p['customer_name']} — ${p['total'] or 0:,.2f}": p["id"]
                    for p in po_results
                }
                picked_po_label = st.selectbox("Results", list(po_label_map.keys()), key="workbench_po_pick")
                selected_po = po_label_map[picked_po_label]

            if selected_po:
                po_detail = qbo_matcher.get_po_full_detail(mc, selected_po)
                st.write(f"PO Number: {po_detail['po_number'] or po_detail['source_file']}")
                if po_detail.get("drive_file_id"):
                    st.markdown(f"[📄 Open original PDF ↗]({gdrive_client.file_view_url(po_detail['drive_file_id'])})")
                st.write(f"Customer: {po_detail['customer_name']}")
                st.write(
                    f"PO Date: {po_detail['po_date'] or '—'} · Sent: {po_detail['sent_date'] or '—'} · "
                    f"Delivery: {po_detail['delivery_date'] or '—'}"
                )
                st.write(
                    f"Subtotal: ${po_detail['subtotal'] or 0:,.2f} · Tax: ${po_detail['tax'] or 0:,.2f} · "
                    f"Total: ${po_detail['total'] or 0:,.2f}"
                )
                _items_table(po_detail["items"])

        with wc2:
            st.markdown("**QuickBooks Invoice**")
            default_customer = po_detail["customer_name"] if po_detail else ""
            inv_customer = st.text_input("Customer", value=default_customer or "", key="workbench_inv_customer")
            inv_query = st.text_input("Search invoice #", key="workbench_inv_query")
            ic1, ic2 = st.columns(2)
            amount_min = ic1.number_input("Min $", value=0.0, step=10.0, key="workbench_inv_min")
            amount_max = ic2.number_input("Max $ (0 = no limit)", value=0.0, step=10.0, key="workbench_inv_max")
            ic3, ic4 = st.columns(2)
            include_voided = ic3.checkbox("Include voided/zero-$ invoices", key="workbench_inv_voided")
            inv_include_matched = ic4.checkbox("Include already-matched invoices", key="workbench_inv_include_matched")
            inv_results = qbo_matcher.search_invoices(
                mc, customer=inv_customer, query=inv_query,
                amount_min=(amount_min or None), amount_max=(amount_max or None),
                include_voided=include_voided, include_matched=inv_include_matched, limit=100,
            )
            if not inv_results:
                st.caption("No matching invoices.")
            else:
                inv_label_map = {
                    f"{i['doc_number']} — {i['customer_name']} — {i['txn_date']} — ${i['total_amt'] or 0:,.2f}": i["id"]
                    for i in inv_results
                }
                picked_inv_label = st.selectbox("Results", list(inv_label_map.keys()), key="workbench_inv_pick")
                selected_invoice = inv_label_map[picked_inv_label]

            if selected_invoice:
                inv_detail = qbo_matcher.get_invoice_full_detail(mc, selected_invoice)
                st.write(f"Invoice #: {inv_detail['doc_number']}")
                st.markdown(f"[Open in QuickBooks ↗]({qbo_client.invoice_url(inv_detail['qbo_invoice_id'])})")
                st.write(f"Customer: {inv_detail['customer_name']}")
                st.write(f"Invoice Date: {inv_detail['txn_date'] or '—'} · Due: {inv_detail['due_date'] or '—'}")
                st.write(f"Total: ${inv_detail['total_amt'] or 0:,.2f}")
                if inv_detail.get("private_note"):
                    st.caption(f"Note: {inv_detail['private_note']}")
                _items_table(inv_detail["items"])

        if selected_po and selected_invoice:
            st.markdown("---")
            replace_existing = False
            existing_po_links = qbo_matcher.get_confirmed_invoices_for_po(mc, selected_po)
            if existing_po_links:
                names = ", ".join(f"{l['doc_number']} (${l['total_amt'] or 0:,.2f})" for l in existing_po_links)
                st.warning(f"This PO is already confirmed-linked to: {names}")
                replace_existing = st.checkbox("Replace existing link(s) with this one", key="workbench_replace")

            other_po = qbo_matcher.get_confirmed_po_for_invoice(mc, selected_invoice)
            if other_po and other_po["id"] != selected_po:
                st.warning(
                    f"This invoice is already confirmed to a different PO: "
                    f"{other_po['po_number'] or other_po['source_file']}. Linking it here too is "
                    f"allowed (e.g. split shipments) but double-check this is intentional."
                )

            if st.button("🔗 Link these"):
                qbo_matcher.manual_link(mc, selected_po, selected_invoice, replace_existing=replace_existing)
                st.success("Linked.")
                st.rerun()
    finally:
        mc.close()
