"""📊 Reports → Products. Phase 2: page_header/section_card/empty_state polish.
Also hosts "Manage products" — the persistent, dashboard-wide product visibility
toggle (a hidden product is excluded from every reporting surface app-wide, but
Edit PO and the QuickBooks pages are unaffected; see dashboard/data.py's
hidden_products table and schema.sql)."""

import plotly.express as px
import streamlit as st

from data import load_hidden_products, month_over_month_movers, set_product_hidden, style
from ui_kit import (
    data_table,
    empty_state,
    entity_comparison,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
)


def _manage_products(ctx) -> None:
    all_names = sorted(
        (
            set(ctx.all_items["product_name"].dropna().unique().tolist())
            | set(ctx.inv_items_all.loc[
                ctx.inv_items_all["category"] == "product", "product_name"
            ].dropna().unique().tolist())
        )
        - {"UNKNOWN"}
    )
    if not all_names:
        st.caption("No products found yet.")
        return

    cols = st.columns(3)
    for i, name in enumerate(all_names):
        is_hidden = name in ctx.hidden_products
        with cols[i % 3]:
            visible = st.checkbox(name, value=not is_hidden, key=f"product_visible_{name}")
        if visible == is_hidden:  # checkbox result no longer matches current DB state -> just toggled
            set_product_hidden(name, hidden=not visible)
            load_hidden_products.clear()
            st.rerun()


def render(ctx) -> None:
    f_inv_items, palette = ctx.f_inv_items, ctx.palette
    by_product_inv, product_colors = ctx.by_product_inv, ctx.product_colors

    page_scaffold("Products", "Revenue, quantity, and mix by product and container size, for the current scope.")
    scope_bar(ctx.fs, order_count=int(ctx.f_inv["id"].nunique()))

    with section_card(
        "⚙️ Manage products",
        "Hide a product to exclude it from every report, chart, filter, and export "
        "app-wide — persists for everyone until turned back on. Edit PO and the "
        "QuickBooks pages are unaffected.",
    ):
        _manage_products(ctx)

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

    with section_card("🆚 Compare products", "Pick two or more products to compare quantity and revenue side by side."):
        product_options_all = sorted(by_product_inv["product_name"].dropna().unique().tolist())
        entity_comparison(
            f_inv_items, "product_name", "Product", product_options_all, "effective_date",
            [("Quantity", "quantity", "sum"), ("Revenue ($)", "line_total", "sum")],
            palette, key="cmp_products",
        )

    with section_card("Product mix over time (quantity)", "Click a bar for a product/customer breakdown."):
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
            period_drilldown(
                fig3, "chart_product_mix_time", by_month_product, "month",
                [("Product", "product_name"), ("Customer", "customer_name")],
                {"Quantity": ("quantity", "sum"), "Revenue ($)": ("line_total", "sum")},
                palette,
            )

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
