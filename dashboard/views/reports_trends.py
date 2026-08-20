"""📊 Reports → Trends. Phase 2: page_header/section_card/empty_state polish."""

import plotly.express as px
import streamlit as st

from data import color_map_for, style
from ui_kit import empty_state, page_header, section_card


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

    with section_card("Invoices per month", "🟠 **Spike** = invoice count more than 1.5× the trailing 3-month average."):
        fig = px.bar(
            by_month, x="month", y="orders", color="spike_label",
            color_discrete_map={"Normal": palette["categorical"][0], "Spike": palette["status"]["warning"]},
            labels={"month": "", "orders": "Invoices", "spike_label": ""},
        )
        st.plotly_chart(style(fig, palette, height=340), use_container_width=True, key="chart_orders_per_month")

    with section_card("Revenue per month"):
        fig2 = px.line(by_month, x="month", y="revenue", labels={"month": "", "revenue": "Revenue ($)"})
        fig2.update_traces(line_color=palette["categorical"][0], line_width=2)
        st.plotly_chart(style(fig2, palette, height=340), use_container_width=True, key="chart_revenue_per_month")

    with section_card("Year-over-year comparison"):
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
            st.plotly_chart(style(fig3, palette, height=340), use_container_width=True, key="chart_yoy")

    st.caption(
        "For a detailed requested-vs-delivered trend (day/week/month, per-customer lines), "
        "see **Requested vs Delivered** under **📦 Fulfillment**."
    )
