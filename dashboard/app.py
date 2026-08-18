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
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = psycopg2.connect(get_database_url())
    try:
        po_df = pd.read_sql_query("SELECT * FROM purchase_orders", conn)
        items_df = pd.read_sql_query("SELECT * FROM line_items", conn)
    finally:
        conn.close()
    return po_df, items_df


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


po_df, items_df = load_data()

if po_df.empty:
    st.info("No data yet — run `python sync_dashboard.py` after your first extraction batch.")
    st.stop()

valid_po, latest_po, all_items, latest_items = prepare(po_df, items_df)

# ── Sidebar: appearance ──────────────────────────────────────────────────────────

theme = st.sidebar.radio("🌗 Theme", ["Light", "Dark"], horizontal=True, key="theme_choice")
palette = DARK if theme == "Dark" else LIGHT

if theme == "Dark":
    st.markdown(
        f"""
        <style>
        [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
            background-color: {palette["page_plane"]};
            color: {palette["ink_primary"]};
        }}
        [data-testid="stSidebar"] {{
            background-color: {palette["surface"]};
            color: {palette["ink_primary"]};
        }}
        [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{
            color: {palette["ink_primary"]} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

st.sidebar.divider()

# ── Sidebar: filters ─────────────────────────────────────────────────────────────

st.sidebar.header("Filters")

min_date = latest_po["effective_date"].min()
max_date = latest_po["effective_date"].max()
has_dates = pd.notna(min_date) and pd.notna(max_date)

DATE_PRESETS = ["Last 30 days", "Last 90 days", "Year to date", "All time", "Custom"]
preset = st.sidebar.selectbox("Date range", DATE_PRESETS, index=3, key="date_preset")

if has_dates:
    today = pd.Timestamp(max_date.date())
    if preset == "Last 30 days":
        start_ts, end_ts = today - pd.Timedelta(days=29), today
    elif preset == "Last 90 days":
        start_ts, end_ts = today - pd.Timedelta(days=89), today
    elif preset == "Year to date":
        start_ts, end_ts = pd.Timestamp(year=today.year, month=1, day=1), today
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

customers = sorted(latest_po["customer_name"].dropna().unique().tolist())
selected_customers = st.sidebar.multiselect("Customer", customers, default=[], key="filter_customers")

products = sorted(latest_items["product_name"].dropna().unique().tolist())
selected_products = st.sidebar.multiselect("Product", products, default=[], key="filter_products")

include_samples = st.sidebar.checkbox("Include samples", value=False, key="include_samples")

fc1, fc2 = st.sidebar.columns(2)
if fc1.button("🔄 Refresh data"):
    load_data.clear()
    st.rerun()
if fc2.button("✖️ Clear filters"):
    for key in ("filter_customers", "filter_products", "date_preset", "custom_range", "include_samples"):
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

product_colors = color_map_for(latest_items["product_name"].dropna().unique().tolist(), palette)

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

st.title("🌱 Garfield Produce — Purchase Order Dashboard")

(tab_overview, tab_trends, tab_products, tab_customers, tab_revisions, tab_data, tab_edit,
 tab_qbo, tab_fulfillment) = st.tabs(
    ["Overview", "Trends", "Products", "Customers", "Revisions & Data Quality", "Raw Data",
     "✏️ Edit", "🔗 QuickBooks", "📦 Requested vs Shipped"]
)

# ── Overview ─────────────────────────────────────────────────────────────────────

with tab_overview:
    total_orders = f_po["id"].nunique()
    total_revenue = f_po["total"].sum()
    unique_customers = f_po["customer_name"].nunique()
    distinct_products = f_items["product_name"].nunique()
    avg_order_value = f_po["total"].mean() if total_orders else 0
    needs_review = int(f_po["math_check_failed"].sum())
    extraction_errors = int(po_df["error"].notna().sum())

    delta_orders = delta_revenue = delta_aov = None
    if start_ts is not None and end_ts is not None:
        span = end_ts - start_ts
        prev_end = start_ts - pd.Timedelta(days=1)
        prev_start = prev_end - span
        prev_po = latest_po[(latest_po["effective_date"] >= prev_start) & (latest_po["effective_date"] <= prev_end)]
        if selected_customers:
            prev_po = prev_po[prev_po["customer_name"].isin(selected_customers)]
        prev_orders = prev_po["id"].nunique()
        if prev_orders:
            delta_orders = total_orders - prev_orders
            delta_revenue = total_revenue - prev_po["total"].sum()
            delta_aov = avg_order_value - prev_po["total"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Orders", f"{total_orders:,}", delta=fmt_delta(delta_orders))
    c2.metric("Total Revenue", f"${total_revenue:,.0f}", delta=fmt_delta(delta_revenue, prefix="$"))
    c3.metric("Customers", f"{unique_customers:,}")
    c4.metric("Products", f"{distinct_products:,}")

    c5, c6, c7 = st.columns(3)
    c5.metric("Avg Order Value", f"${avg_order_value:,.2f}", delta=fmt_delta(delta_aov, prefix="$", decimals=2))
    c6.metric("⚠️ Needs Review (math check)", f"{needs_review:,}")
    c7.metric("❌ Extraction Errors", f"{extraction_errors:,}")

    if needs_review or extraction_errors:
        st.caption("See the **Revisions & Data Quality** tab for details on flagged orders.")
    if start_ts is not None and end_ts is not None:
        st.caption("Deltas compare the selected date range to the immediately preceding period of equal length.")

    st.divider()
    st.subheader("Export")
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        pd.DataFrame({
            "Metric": ["Orders", "Total Revenue", "Customers", "Products", "Avg Order Value",
                       "Needs Review (math check)", "Extraction Errors"],
            "Value": [total_orders, total_revenue, unique_customers, distinct_products,
                      avg_order_value, needs_review, extraction_errors],
        }).to_excel(writer, sheet_name="Overview", index=False)
        strip_tz(f_po.drop(columns=["po_key"], errors="ignore")).to_excel(writer, sheet_name="Orders", index=False)
        strip_tz(f_items).to_excel(writer, sheet_name="Line Items", index=False)
        by_product.to_excel(writer, sheet_name="Products", index=False)
        by_customer.to_excel(writer, sheet_name="Customers", index=False)
    st.download_button(
        "📊 Export full report (Excel)",
        excel_buf.getvalue(),
        file_name="gpc_po_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_excel",
    )
    st.caption("Reflects the filters currently applied in the sidebar.")

# ── Trends ───────────────────────────────────────────────────────────────────────

with tab_trends:
    monthly = f_po.dropna(subset=["effective_date"]).copy()
    monthly["month"] = monthly["effective_date"].dt.to_period("M").dt.to_timestamp()
    by_month = monthly.groupby("month").agg(orders=("id", "nunique"), revenue=("total", "sum")).reset_index()
    by_month = by_month.sort_values("month")

    if by_month.empty:
        st.info("Not enough dated orders in the current filter to show trends.")
    else:
        by_month["rolling_avg"] = by_month["orders"].rolling(3, min_periods=1).mean().shift(1)
        by_month["is_spike"] = by_month["orders"] > (by_month["rolling_avg"].fillna(0) * 1.5)
        by_month["spike_label"] = by_month["is_spike"].map({True: "Spike", False: "Normal"})

        st.subheader("Orders per month")
        fig = px.bar(
            by_month, x="month", y="orders", color="spike_label",
            color_discrete_map={"Normal": palette["categorical"][0], "Spike": palette["status"]["warning"]},
            labels={"month": "", "orders": "Orders", "spike_label": ""},
        )
        st.plotly_chart(style(fig, palette), use_container_width=True)
        st.caption("🟠 **Spike** = order count more than 1.5× the trailing 3-month average.")

        st.subheader("Revenue per month")
        fig2 = px.line(by_month, x="month", y="revenue", labels={"month": "", "revenue": "Revenue ($)"})
        fig2.update_traces(line_color=palette["categorical"][0], line_width=2)
        st.plotly_chart(style(fig2, palette), use_container_width=True)

        st.subheader("Year-over-year comparison")
        yoy_src = f_po.dropna(subset=["effective_date"]).copy()
        yoy_src["year"] = yoy_src["effective_date"].dt.year.astype(str)
        yoy_src["moy"] = yoy_src["effective_date"].dt.month
        yoy = yoy_src.groupby(["year", "moy"]).agg(revenue=("total", "sum")).reset_index()
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
            st.plotly_chart(style(fig3, palette), use_container_width=True)

# ── Products ─────────────────────────────────────────────────────────────────────

with tab_products:
    if f_items.empty:
        st.info("No line items in the current filter.")
    else:
        st.subheader("Revenue by product")
        fig = px.bar(
            by_product.sort_values("revenue", ascending=True), x="revenue", y="product_name", orientation="h",
            color="product_name", color_discrete_map=product_colors,
            labels={"revenue": "Revenue ($)", "product_name": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, palette), use_container_width=True)
        st.download_button(
            "⬇️ Download product revenue (CSV)",
            by_product.rename(columns={"product_name": "Product", "revenue": "Revenue ($)", "quantity": "Quantity"})
            .to_csv(index=False).encode("utf-8"),
            file_name="revenue_by_product.csv", mime="text/csv", key="dl_products",
        )

        st.subheader("Product mix over time (quantity)")
        by_month_product = f_items.dropna(subset=["effective_date"]).copy()
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
            st.plotly_chart(style(fig3, palette), use_container_width=True)

        st.subheader("Top movers (month over month)")
        movers = month_over_month_movers(f_items, "effective_date", "product_name", "line_total")
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

# ── Customers ────────────────────────────────────────────────────────────────────

with tab_customers:
    if f_po.empty:
        st.info("No orders in the current filter.")
    else:
        st.subheader("Top customers by revenue")
        top = by_customer.sort_values("revenue", ascending=False).head(15).sort_values("revenue")
        fig = px.bar(
            top, x="revenue", y="customer_name", orientation="h",
            labels={"revenue": "Revenue ($)", "customer_name": ""},
        )
        fig.update_traces(marker_color=palette["sequential_blue"][4])
        st.plotly_chart(style(fig, palette), use_container_width=True)

        st.subheader("Customer summary")
        customer_table = by_customer.sort_values("revenue", ascending=False).rename(columns={
            "customer_name": "Customer", "orders": "Orders",
            "revenue": "Revenue ($)", "avg_order_value": "Avg Order ($)",
        })
        st.dataframe(customer_table, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download customer summary (CSV)",
            customer_table.to_csv(index=False).encode("utf-8"),
            file_name="customer_summary.csv", mime="text/csv", key="dl_customers",
        )

        st.subheader("Top movers (month over month)")
        movers = month_over_month_movers(f_po, "effective_date", "customer_name", "total")
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

# ── Revisions & Data Quality ───────────────────────────────────────────────────────

with tab_revisions:
    st.subheader("Orders with revisions")
    rev_po = valid_po[valid_po["is_revision"]]
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
        st.plotly_chart(style(fig_lead, palette), use_container_width=True)

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
    math_fail = valid_po[valid_po["math_check_failed"]]
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

# ── Raw Data ─────────────────────────────────────────────────────────────────────

with tab_data:
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

# ── Edit ─────────────────────────────────────────────────────────────────────────

with tab_edit:
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
                with st.spinner("Pulling invoices from QuickBooks..."):
                    count = qbo_client.sync_invoices(sync_conn, full_resync=full_resync)
                st.success(f"Synced {count} invoice(s).")
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

# ── Requested vs Shipped ─────────────────────────────────────────────────────────

with tab_fulfillment:
    st.caption(
        "Compares PO line items (requested) to matched QuickBooks invoice line items "
        "(shipped), respecting the sidebar filters above. Run matching first — matches "
        "are permanent decisions (confirm/reject), not recomputed from scratch each time."
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

        st.divider()
        po_ids = f_po["id"].tolist()
        if not po_ids:
            st.info("No orders in the current filter.")
        else:
            st.subheader("Requested vs. shipped — by product")
            with mc.cursor() as cur:
                cur.execute(
                    "SELECT qi.product_name, SUM(qi.quantity) FROM po_invoice_links l "
                    "JOIN qbo_invoice_items qi ON qi.invoice_id = l.invoice_id "
                    "WHERE l.confirmed = TRUE AND l.po_id = ANY(%s) GROUP BY qi.product_name",
                    (po_ids,),
                )
                shipped_by_product = {k: float(v or 0) for k, v in cur.fetchall()}
            requested_by_product = f_items.groupby("product_name")["quantity"].sum().to_dict()

            products = sorted(set(requested_by_product) | set(shipped_by_product))
            comp_df = pd.DataFrame({
                "Product": products,
                "Requested": [float(requested_by_product.get(p, 0)) for p in products],
                "Shipped": [shipped_by_product.get(p, 0.0) for p in products],
            })
            comp_long = comp_df.melt(id_vars="Product", value_vars=["Requested", "Shipped"],
                                      var_name="Type", value_name="Quantity")
            fig = px.bar(
                comp_long, x="Product", y="Quantity", color="Type", barmode="group",
                color_discrete_map={"Requested": palette["categorical"][0], "Shipped": palette["categorical"][1]},
                labels={"Product": ""},
            )
            st.plotly_chart(style(fig, palette), use_container_width=True)
            comp_df["Variance"] = comp_df["Shipped"] - comp_df["Requested"]
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

            st.subheader("Requested vs. shipped — by customer")
            with mc.cursor() as cur:
                cur.execute(
                    "SELECT po.customer_name, SUM(qi.quantity) FROM po_invoice_links l "
                    "JOIN purchase_orders po ON po.id = l.po_id "
                    "JOIN qbo_invoice_items qi ON qi.invoice_id = l.invoice_id "
                    "WHERE l.confirmed = TRUE AND l.po_id = ANY(%s) GROUP BY po.customer_name",
                    (po_ids,),
                )
                shipped_by_customer = {k: float(v or 0) for k, v in cur.fetchall()}
            requested_by_customer = f_items.groupby("customer_name")["quantity"].sum().to_dict()

            customers_all = sorted(set(requested_by_customer) | set(shipped_by_customer))
            comp_cust = pd.DataFrame({
                "Customer": customers_all,
                "Requested": [float(requested_by_customer.get(c, 0)) for c in customers_all],
                "Shipped": [shipped_by_customer.get(c, 0.0) for c in customers_all],
            })
            comp_cust_long = comp_cust.melt(id_vars="Customer", value_vars=["Requested", "Shipped"],
                                             var_name="Type", value_name="Quantity")
            fig2 = px.bar(
                comp_cust_long, x="Customer", y="Quantity", color="Type", barmode="group",
                color_discrete_map={"Requested": palette["categorical"][0], "Shipped": palette["categorical"][1]},
                labels={"Customer": ""},
            )
            st.plotly_chart(style(fig2, palette), use_container_width=True)
            comp_cust["Variance"] = comp_cust["Shipped"] - comp_cust["Requested"]
            st.dataframe(comp_cust, use_container_width=True, hide_index=True)

            st.subheader("Matched PO ↔ Invoice detail")
            with mc.cursor() as cur:
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
    finally:
        mc.close()
