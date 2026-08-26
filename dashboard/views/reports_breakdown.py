"""📊 Reports → Breakdown. Phase 2: page_header/section_card polish + segmented_control
period picker (replaces the plain selectbox, per the plan's component vocabulary)."""

import plotly.express as px
import streamlit as st

from data import color_map_for, style
from ui_kit import data_table, empty_state, page_scaffold, period_drilldown, scope_bar, section_card


def render(ctx) -> None:
    f_inv_items, palette = ctx.f_inv_items, ctx.palette

    page_scaffold(
        "Breakdown",
        "Slice revenue and quantity across time, customer, product, and size, in any "
        "combination — the full QuickBooks invoice history, for the current scope.",
    )
    scope_bar(ctx.fs, order_count=int(ctx.f_inv["id"].nunique()))

    bc1, bc2 = st.columns(2)
    b_period = bc1.segmented_control(
        "Time period", ["All time", "Day", "Week", "Month", "Quarter", "Year"],
        default="Month", key="rpt_breakdown_period_sc",
    ) or "Month"
    b_dims = bc2.multiselect(
        "Break down by", ["Customer", "Product", "Size"], default=["Product"], key="rpt_breakdown_dims",
    )

    if f_inv_items.empty:
        empty_state("No line items in the current filter.")
        return

    detail = f_inv_items.dropna(subset=["effective_date"]).copy()
    period_freq = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}
    group_cols = []
    if b_period != "All time":
        detail["Period"] = detail["effective_date"].dt.to_period(period_freq[b_period]).dt.start_time
        group_cols.append("Period")
    dim_col_map = {"Customer": "customer_name", "Product": "product_name", "Size": "container_size"}
    group_cols += [dim_col_map[d] for d in b_dims]

    if not group_cols:
        detail["All"] = "All"
        group_cols = ["All"]

    grouped = detail.groupby(group_cols, as_index=False).agg(
        revenue=("line_total", "sum"), quantity=("quantity", "sum"),
    )
    if "Period" in group_cols:
        grouped = grouped.sort_values(["Period"] + [c for c in group_cols if c != "Period"])
    else:
        grouped = grouped.sort_values("revenue", ascending=False)

    display_df = grouped.rename(columns={
        "customer_name": "Customer", "product_name": "Product", "container_size": "Size",
        "revenue": "Revenue ($)", "quantity": "Quantity",
    })
    if "All" in display_df.columns:
        display_df = display_df.drop(columns=["All"])

    with section_card("Breakdown"):
        data_table(display_df)
        st.download_button(
            "⬇️ Download breakdown (CSV)",
            display_df.to_csv(index=False).encode("utf-8"),
            file_name="business_breakdown.csv", mime="text/csv", key="dl_business_breakdown",
        )

        if b_period != "All time":
            show_by_customer = "Customer" in b_dims
            chart_group_cols = ["Period"] + (["customer_name"] if show_by_customer else [])
            chart_src = detail.groupby(chart_group_cols, as_index=False)["line_total"].sum()
            if show_by_customer:
                fig_bd = px.line(
                    chart_src, x="Period", y="line_total", color="customer_name", markers=True,
                    color_discrete_map=color_map_for(chart_src["customer_name"].dropna().unique().tolist(), palette),
                    labels={"Period": "", "line_total": "Revenue ($)", "customer_name": "Customer"},
                )
            else:
                fig_bd = px.line(
                    chart_src, x="Period", y="line_total", markers=True,
                    labels={"Period": "", "line_total": "Revenue ($)"},
                )
                fig_bd.update_traces(line_color=palette["categorical"][0])
            period_drilldown(
                fig_bd, "chart_business_breakdown", detail, "Period",
                [("Customer", "customer_name"), ("Product", "product_name"), ("Size", "container_size")],
                {"Revenue ($)": ("line_total", "sum"), "Quantity": ("quantity", "sum")},
                palette,
            )
            st.caption(
                "Chart aggregates across product/size even when selected above — see the "
                "table for the full multi-dimensional detail."
                + (" One line per customer." if show_by_customer else "")
            )
