"""
🏠 Home — formerly the "Overview" sub-tab under Reports. Phase 2 added page_header/
kpi_row (with trailing sparklines)/section_card polish. Phase 3 adds the "Needs
attention" digest, ranked across the whole app by dashboard/attention.py.
"""

import io

import pandas as pd
import psycopg2
import streamlit as st

import attention
import qbo_matcher
from data import fmt_delta, get_database_url, load_matched_line_items, strip_tz, yoy_annual_chart
from ui_kit import kpi_row, page_header, section_card, severity_badge, yoy_drilldown

_SPARKLINE_MONTHS = 6


def _trailing_monthly(f_inv: pd.DataFrame, value_col: str, agg: str) -> list[float]:
    """Last _SPARKLINE_MONTHS months of a metric, oldest first, for a KPI sparkline.
    Returns [] if there isn't enough dated data — kpi_row skips the sparkline then."""
    dated = f_inv.dropna(subset=["effective_date"])
    if dated.empty:
        return []
    monthly = dated.copy()
    monthly["month"] = monthly["effective_date"].dt.to_period("M")
    if agg == "nunique":
        series = monthly.groupby("month")["id"].nunique()
    else:
        series = monthly.groupby("month")[value_col].sum()
    series = series.sort_index().tail(_SPARKLINE_MONTHS)
    return series.tolist() if len(series) >= 2 else []


def render(ctx) -> None:
    f_inv, f_inv_items = ctx.f_inv, ctx.f_inv_items
    f_po, f_items, po_df = ctx.f_po, ctx.f_items, ctx.po_df
    palette = ctx.palette
    start_ts, end_ts = ctx.start_ts, ctx.end_ts
    selected_customers = ctx.selected_customers
    invoices = ctx.invoices
    by_product_inv, by_customer_inv = ctx.by_product_inv, ctx.by_customer_inv

    page_header("Garfield Produce — Purchase Order Dashboard")

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

    kpi_row([
        {
            "label": "Invoices", "value": f"{total_invoices:,}", "delta": fmt_delta(delta_invoices),
            "chart_data": _trailing_monthly(f_inv, "id", "nunique"), "chart_type": "bar",
        },
        {
            "label": "Total Revenue", "value": f"${total_revenue:,.0f}", "delta": fmt_delta(delta_revenue, prefix="$"),
            "chart_data": _trailing_monthly(f_inv, "total_amt", "sum"), "chart_type": "line",
        },
        {"label": "Customers", "value": f"{unique_customers:,}"},
        {"label": "Products", "value": f"{distinct_products:,}"},
    ])

    st.metric("Avg Invoice Value", f"${avg_invoice_value:,.2f}", delta=fmt_delta(delta_aiv, prefix="$", decimals=2))
    if start_ts is not None and end_ts is not None:
        st.caption("Deltas compare the selected date range to the immediately preceding period of equal length.")

    with section_card("🔔 Needs attention", "Ranked across the whole business — biggest issues first."):
        _conn = psycopg2.connect(get_database_url())
        try:
            needs_review_rows = qbo_matcher.get_needs_review(_conn)
            unlinked_pos = qbo_matcher.get_unlinked_pos(_conn)
        finally:
            _conn.close()
        attention_items = attention.collect_attention_items(
            ctx, matched_line_items_df=load_matched_line_items(),
            needs_review_rows=needs_review_rows, unlinked_pos=unlinked_pos,
        )
        if not attention_items:
            st.caption("Nothing needs attention right now. 🎉")
        else:
            for item in attention_items:
                ic1, ic2, ic3 = st.columns([1, 5, 2])
                with ic1:
                    severity_badge(item.severity)
                ic2.write(item.title)
                target_page = ctx.pages.get(item.page)
                if target_page is not None:
                    with ic3:
                        st.page_link(target_page, label="Review →")

    needs_review = int(f_po["math_check_failed"].sum())
    extraction_errors = int(po_df["error"].notna().sum())
    with section_card("📋 PO extraction data quality", "Only covers the subset of orders with a formal PO document — not the metrics above."):
        kpi_row([
            {"label": "⚠️ Needs Review (math check)", "value": f"{needs_review:,}"},
            {"label": "❌ Extraction Errors", "value": f"{extraction_errors:,}"},
        ])
        if needs_review or extraction_errors:
            st.caption("See the **Data Quality** page (under 📦 Fulfillment) for details on flagged orders.")

    current_year = str(pd.Timestamp.now().year)
    yoy_breakdown_dims = [("Customer", "customer_name")]
    yoy_agg_spec = {"Invoices": ("id", "nunique"), "Revenue ($)": ("total_amt", "sum")}
    with section_card(
        "📈 Annual comparison",
        f"{current_year} vs. each prior year, by calendar month — {current_year} is bold, "
        "past years are muted for reference. Respects the sidebar filters above. "
        "Click a point for a customer breakdown.",
    ):
        ac1, ac2 = st.columns(2)
        with ac1:
            st.caption("Revenue")
            fig_rev_yoy = yoy_annual_chart(f_inv, "effective_date", "total_amt", "sum", "Revenue ($)", palette, current_year)
            if fig_rev_yoy is not None:
                yoy_drilldown(
                    fig_rev_yoy, "chart_overview_revenue_yoy", f_inv, "effective_date",
                    yoy_breakdown_dims, yoy_agg_spec, palette, height=320,
                )
            else:
                st.caption("Not enough dated invoices in the current filter.")
        with ac2:
            st.caption("Invoices")
            fig_inv_yoy = yoy_annual_chart(f_inv, "effective_date", "id", "nunique", "Invoices", palette, current_year)
            if fig_inv_yoy is not None:
                yoy_drilldown(
                    fig_inv_yoy, "chart_overview_orders_yoy", f_inv, "effective_date",
                    yoy_breakdown_dims, yoy_agg_spec, palette, height=320,
                )
            else:
                st.caption("Not enough dated invoices in the current filter.")

    with section_card("Export", "Reflects the filters currently applied in the sidebar."):
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
