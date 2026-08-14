#!/usr/bin/env python3
"""
Garfield Produce Company — PO Dashboard

Reads from the hosted Postgres database populated by sync_dashboard.py.
Run locally with:  streamlit run dashboard/app.py   (from the repo root)
"""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st

st.set_page_config(page_title="Garfield Produce — PO Dashboard", layout="wide", page_icon="🌱")

# ── Palette (validated colorblind-safe set — see dataviz skill / schema.sql sibling) ──
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
INK_PRIMARY = "#0b0b0b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def style(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=INK_PRIMARY, family=FONT_FAMILY),
        xaxis=dict(gridcolor=GRID, linecolor=INK_MUTED, zeroline=False),
        yaxis=dict(gridcolor=GRID, linecolor=INK_MUTED, zeroline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor=SURFACE, font_family=FONT_FAMILY),
    )
    return fig


def color_map_for(categories: list[str]) -> dict:
    """Fixed hue per category (alphabetical order) so a category keeps its color
    across every chart and across filter changes — never repainted."""
    ordered = sorted(categories)
    colors = {}
    for i, cat in enumerate(ordered):
        colors[cat] = CATEGORICAL[i] if i < len(CATEGORICAL) else INK_MUTED
    return colors


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

def get_database_url() -> str:
    url = st.secrets.get("database_url") or os.environ.get("DATABASE_URL")
    if not url:
        st.error("No database configured. Set `database_url` in .streamlit/secrets.toml.")
        st.stop()
    return url


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

# ── Sidebar filters ──────────────────────────────────────────────────────────────

st.sidebar.header("Filters")

min_date = latest_po["effective_date"].min()
max_date = latest_po["effective_date"].max()
date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date.date(), max_date.date()) if pd.notna(min_date) and pd.notna(max_date) else None,
)

customers = sorted(latest_po["customer_name"].dropna().unique().tolist())
selected_customers = st.sidebar.multiselect("Customer", customers, default=[])

products = sorted(latest_items["product_name"].dropna().unique().tolist())
selected_products = st.sidebar.multiselect("Product", products, default=[])

include_samples = st.sidebar.checkbox("Include samples", value=False)

if st.sidebar.button("🔄 Refresh data"):
    load_data.clear()
    st.rerun()

# Apply filters
f_po = latest_po.copy()
f_items = latest_items.copy()

if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    f_po = f_po[(f_po["effective_date"] >= start) & (f_po["effective_date"] <= end)]
    f_items = f_items[f_items["po_id"].isin(f_po["id"])]

if selected_customers:
    f_po = f_po[f_po["customer_name"].isin(selected_customers)]
    f_items = f_items[f_items["po_id"].isin(f_po["id"])]

if selected_products:
    f_items = f_items[f_items["product_name"].isin(selected_products)]

if not include_samples:
    f_items = f_items[~f_items["is_sample"]]

product_colors = color_map_for(latest_items["product_name"].dropna().unique().tolist())

st.title("🌱 Garfield Produce — Purchase Order Dashboard")

tab_overview, tab_trends, tab_products, tab_customers, tab_revisions, tab_data = st.tabs(
    ["Overview", "Trends", "Products", "Customers", "Revisions & Data Quality", "Raw Data"]
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Orders", f"{total_orders:,}")
    c2.metric("Total Revenue", f"${total_revenue:,.0f}")
    c3.metric("Customers", f"{unique_customers:,}")
    c4.metric("Products", f"{distinct_products:,}")

    c5, c6, c7 = st.columns(3)
    c5.metric("Avg Order Value", f"${avg_order_value:,.2f}")
    c6.metric("⚠️ Needs Review (math check)", f"{needs_review:,}")
    c7.metric("❌ Extraction Errors", f"{extraction_errors:,}")

    if needs_review or extraction_errors:
        st.caption("See the **Revisions & Data Quality** tab for details on flagged orders.")

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
            color_discrete_map={"Normal": CATEGORICAL[0], "Spike": STATUS["warning"]},
            labels={"month": "", "orders": "Orders", "spike_label": ""},
        )
        st.plotly_chart(style(fig), use_container_width=True)
        st.caption("🟠 **Spike** = order count more than 1.5× the trailing 3-month average.")

        st.subheader("Revenue per month")
        fig2 = px.line(by_month, x="month", y="revenue", labels={"month": "", "revenue": "Revenue ($)"})
        fig2.update_traces(line_color=CATEGORICAL[0], line_width=2)
        st.plotly_chart(style(fig2), use_container_width=True)

# ── Products ─────────────────────────────────────────────────────────────────────

with tab_products:
    if f_items.empty:
        st.info("No line items in the current filter.")
    else:
        by_product = (
            f_items.groupby("product_name")
            .agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
            .reset_index()
            .sort_values("revenue", ascending=True)
        )

        st.subheader("Revenue by product")
        fig = px.bar(
            by_product, x="revenue", y="product_name", orientation="h",
            color="product_name", color_discrete_map=product_colors,
            labels={"revenue": "Revenue ($)", "product_name": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig), use_container_width=True)

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
            st.plotly_chart(style(fig3), use_container_width=True)

# ── Customers ────────────────────────────────────────────────────────────────────

with tab_customers:
    if f_po.empty:
        st.info("No orders in the current filter.")
    else:
        by_customer = (
            f_po.groupby("customer_name")
            .agg(orders=("id", "nunique"), revenue=("total", "sum"))
            .reset_index()
            .sort_values("revenue", ascending=False)
        )

        st.subheader("Top customers by revenue")
        top = by_customer.head(15).sort_values("revenue")
        fig = px.bar(
            top, x="revenue", y="customer_name", orientation="h",
            labels={"revenue": "Revenue ($)", "customer_name": ""},
        )
        fig.update_traces(marker_color=SEQUENTIAL_BLUE[4])
        st.plotly_chart(style(fig), use_container_width=True)

        st.subheader("Customer summary")
        by_customer["avg_order_value"] = (by_customer["revenue"] / by_customer["orders"]).round(2)
        st.dataframe(
            by_customer.rename(columns={
                "customer_name": "Customer", "orders": "Orders",
                "revenue": "Revenue ($)", "avg_order_value": "Avg Order ($)",
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
        show = rev_po[["po_number", "version_label", "effective_date", "customer_name", "total", "source_file"]]
        st.dataframe(
            show.rename(columns={
                "po_number": "PO Number", "version_label": "Version", "effective_date": "Date",
                "customer_name": "Customer", "total": "Total ($)", "source_file": "Source File",
            }),
            use_container_width=True, hide_index=True,
        )

    st.subheader("⚠️ Math check failures")
    math_fail = valid_po[valid_po["math_check_failed"]]
    if math_fail.empty:
        st.caption("None — arithmetic on every order checks out.")
    else:
        st.dataframe(
            math_fail[["po_number", "source_file", "customer_name", "math_check_detail"]].rename(columns={
                "po_number": "PO Number", "source_file": "Source File",
                "customer_name": "Customer", "math_check_detail": "Issue",
            }),
            use_container_width=True, hide_index=True,
        )

    st.subheader("❌ Extraction errors")
    errored = po_df[po_df["error"].notna()]
    if errored.empty:
        st.caption("None — every file extracted successfully.")
    else:
        st.dataframe(
            errored[["source_file", "error"]].rename(columns={"source_file": "Source File", "error": "Error"}),
            use_container_width=True, hide_index=True,
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
    )
