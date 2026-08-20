"""
📊 Reports → Trends. Phase 2 added page_header/section_card/empty_state polish.
Every time-series chart here is click-to-drill-down (click a bar/point to see a
customer breakdown for that period below it) with hover enriched to show the top
customer at a glance — see dashboard/ui_kit.py's period_drilldown/yoy_drilldown.
"""

import plotly.express as px
import streamlit as st

from data import color_map_for, top_entity_per_period
from ui_kit import empty_state, page_header, period_drilldown, section_card, yoy_drilldown


def render(ctx) -> None:
    f_inv, palette = ctx.f_inv, ctx.palette

    page_header(
        "Trends",
        "Invoice volume and revenue over time — the full QuickBooks invoice history, "
        "respecting the sidebar filters above.",
    )

    monthly = f_inv.dropna(subset=["effective_date"]).copy()
    monthly["month"] = monthly["effective_date"].dt.to_period("M").dt.to_timestamp()
    by_month = monthly.groupby("month").agg(orders=("id", "nunique"), revenue=("total_amt", "sum")).reset_index()
    by_month = by_month.sort_values("month")

    if by_month.empty:
        empty_state("Not enough dated invoices in the current filter to show trends.")
        return

    by_month["rolling_avg"] = by_month["orders"].rolling(3, min_periods=1).mean().shift(1)
    by_month["is_spike"] = by_month["orders"] > (by_month["rolling_avg"].fillna(0) * 1.5)
    by_month["spike_label"] = by_month["is_spike"].map({True: "Spike", False: "Normal"})
    by_month = by_month.merge(
        top_entity_per_period(monthly, "month", "customer_name", "id", "nunique").rename("Top customer"),
        left_on="month", right_index=True, how="left",
    )

    breakdown_dims = [("Customer", "customer_name")]
    agg_spec = {"Invoices": ("id", "nunique"), "Revenue ($)": ("total_amt", "sum")}

    with section_card(
        "Invoices per month",
        "🟠 **Spike** = invoice count more than 1.5× the trailing 3-month average. "
        "Click a bar for a customer breakdown.",
    ):
        fig = px.bar(
            by_month, x="month", y="orders", color="spike_label", hover_data={"Top customer": True},
            color_discrete_map={"Normal": palette["categorical"][0], "Spike": palette["status"]["warning"]},
            labels={"month": "", "orders": "Invoices", "spike_label": ""},
        )
        period_drilldown(fig, "chart_orders_per_month", monthly, "month", breakdown_dims, agg_spec, palette)

    with section_card("Revenue per month", "Click a point for a customer breakdown."):
        fig2 = px.line(by_month, x="month", y="revenue", hover_data={"Top customer": True}, labels={"month": "", "revenue": "Revenue ($)"})
        fig2.update_traces(line_color=palette["categorical"][0], line_width=2)
        period_drilldown(fig2, "chart_revenue_per_month", monthly, "month", breakdown_dims, agg_spec, palette)

    with section_card("Year-over-year comparison", "Click a point for a customer breakdown."):
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
            yoy_drilldown(fig3, "chart_yoy", yoy_src, "effective_date", breakdown_dims, agg_spec, palette)

    st.caption(
        "For a detailed requested-vs-delivered trend (day/week/month, per-customer lines), "
        "see **Requested vs Delivered** under **📦 Fulfillment**."
    )
