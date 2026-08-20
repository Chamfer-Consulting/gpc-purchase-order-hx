"""📊 Reports → Products. Phase 2: page_header/section_card/empty_state polish."""

import plotly.express as px
import streamlit as st

from data import month_over_month_movers, style
from ui_kit import data_table, empty_state, page_header, section_card


def render(ctx) -> None:
    f_inv_items, palette = ctx.f_inv_items, ctx.palette
    by_product_inv, product_colors = ctx.by_product_inv, ctx.product_colors

    page_header("Products", "Revenue, quantity, and mix by product — respects the sidebar filters above.")

    if f_inv_items.empty:
        empty_state("No line items in the current filter.")
        return

    with section_card("Revenue by product"):
        fig = px.bar(
            by_product_inv.sort_values("revenue", ascending=True), x="revenue", y="product_name", orientation="h",
            color="product_name", color_discrete_map=product_colors,
            labels={"revenue": "Revenue ($)", "product_name": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, palette, height=380), use_container_width=True, key="chart_revenue_by_product")
        st.download_button(
            "⬇️ Download product revenue (CSV)",
            by_product_inv.rename(columns={"product_name": "Product", "revenue": "Revenue ($)", "quantity": "Quantity"})
            .to_csv(index=False).encode("utf-8"),
            file_name="revenue_by_product.csv", mime="text/csv", key="dl_products",
        )

    with section_card("Product mix over time (quantity)"):
        by_month_product = f_inv_items.dropna(subset=["effective_date"]).copy()
        by_month_product["month"] = by_month_product["effective_date"].dt.to_period("M").dt.to_timestamp()
        mix = by_month_product.groupby(["month", "product_name"])["quantity"].sum().reset_index()
        if mix.empty:
            st.caption("Not enough dated line items to show product mix over time.")
        else:
            fig3 = px.bar(
                mix, x="month", y="quantity", color="product_name",
                color_discrete_map=product_colors,
                labels={"month": "", "quantity": "Quantity", "product_name": "Product"},
            )
            st.plotly_chart(style(fig3, palette, height=340), use_container_width=True, key="chart_product_mix_time")

    with section_card("Top movers (month over month)"):
        movers = month_over_month_movers(f_inv_items, "effective_date", "product_name", "line_total")
        if movers is None:
            st.caption("Need at least two distinct months of data in the current filter to compare.")
        else:
            mdf, curr_m, prev_m = movers
            st.caption(f"Comparing **{curr_m}** to **{prev_m}**.")
            data_table(
                mdf[["product_name", "prev", "curr", "Change"]].rename(columns={
                    "product_name": "Product", "prev": f"{prev_m} Revenue ($)", "curr": f"{curr_m} Revenue ($)",
                }),
            )
