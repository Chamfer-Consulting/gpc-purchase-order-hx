"""Reports → Customers. Phase 2: page_header/section_card/empty_state polish."""

import plotly.express as px
import streamlit as st

from data import PLOTLY_CONFIG, color_map_for, month_over_month_movers, style
from ui_kit import (
    data_table,
    empty_state,
    entity_comparison,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
)


def render(ctx) -> None:
    f_inv, f_inv_items, palette = ctx.f_inv, ctx.f_inv_items, ctx.palette
    by_customer_inv, product_colors, inv_items_all = ctx.by_customer_inv, ctx.product_colors, ctx.inv_items_all

    page_scaffold("Customers", "Revenue, order volume, and product mix by customer, for the current scope.")
    scope_bar(ctx.fs, order_count=int(f_inv["id"].nunique()))

    if f_inv.empty:
        empty_state("No invoices in the current filter.")
        return

    with section_card("Top customers by revenue"):
        top = by_customer_inv.sort_values("revenue", ascending=False).head(15).sort_values("revenue")
        fig = px.bar(
            top, x="revenue", y="customer_name", orientation="h",
            labels={"revenue": "Revenue ($)", "customer_name": ""},
        )
        fig.update_traces(marker_color=palette["sequential_blue"][4])
        st.plotly_chart(style(fig, palette, height=380), use_container_width=True, config=PLOTLY_CONFIG, key="chart_top_customers")

    with section_card("Compare customers", "Pick two or more customers to compare revenue and invoice volume side by side."):
        cust_options_all = sorted(by_customer_inv["customer_name"].dropna().unique().tolist())
        entity_comparison(
            f_inv, "customer_name", "Customer", cust_options_all, "effective_date",
            [("Revenue ($)", "total_amt", "sum"), ("Invoices", "id", "nunique")],
            palette, key="cmp_customers",
        )

    cust_month = f_inv.dropna(subset=["effective_date"]).copy()
    cust_month["month"] = cust_month["effective_date"].dt.to_period("M").dt.to_timestamp()

    cust_breakdown_dims = [("Customer", "customer_name")]
    cust_agg_spec = {"Invoices": ("id", "nunique"), "Revenue ($)": ("total_amt", "sum")}

    with section_card("Customer revenue over time", "Click a point for a per-customer breakdown."):
        rev_over_time = cust_month.groupby(["month", "customer_name"], as_index=False)["total_amt"].sum()
        if rev_over_time.empty:
            st.caption("Not enough dated invoices in the current filter to show revenue over time.")
        else:
            fig_rev_time = px.line(
                rev_over_time, x="month", y="total_amt", color="customer_name", markers=True,
                color_discrete_map=color_map_for(rev_over_time["customer_name"].dropna().unique().tolist(), palette),
                labels={"month": "", "total_amt": "Revenue ($)", "customer_name": "Customer"},
            )
            period_drilldown(fig_rev_time, "chart_customer_revenue_time", cust_month, "month", cust_breakdown_dims, cust_agg_spec, palette)

    with section_card("Customer invoices over time", "Click a point for a per-customer breakdown."):
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
            period_drilldown(fig_orders_time, "chart_customer_orders_time", cust_month, "month", cust_breakdown_dims, cust_agg_spec, palette)

    with section_card("Product mix over time, by customer", "Pick a customer to see what they've bought, by product, over time."):
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
                st.plotly_chart(style(fig_cust_mix, palette, height=340), use_container_width=True, config=PLOTLY_CONFIG, key="chart_customer_product_mix_time")

    with section_card("Customer summary"):
        customer_table = by_customer_inv.sort_values("revenue", ascending=False).rename(columns={
            "customer_name": "Customer", "invoices": "Invoices",
            "revenue": "Revenue ($)", "avg_invoice_value": "Avg Invoice ($)",
        })
        data_table(customer_table)
        st.download_button(
            "Download customer summary (CSV)",
            customer_table.to_csv(index=False).encode("utf-8"),
            file_name="customer_summary.csv", mime="text/csv", key="dl_customers",
        )

    with section_card("Top movers (month over month)"):
        movers = month_over_month_movers(f_inv, "effective_date", "customer_name", "total_amt")
        if movers is None:
            st.caption("Need at least two distinct months of data in the current filter to compare.")
        else:
            mdf, curr_m, prev_m = movers
            st.caption(f"Comparing **{curr_m}** to **{prev_m}**.")
            data_table(
                mdf[["customer_name", "prev", "curr", "Change"]].rename(columns={
                    "customer_name": "Customer", "prev": f"{prev_m} Revenue ($)", "curr": f"{curr_m} Revenue ($)",
                }),
            )
