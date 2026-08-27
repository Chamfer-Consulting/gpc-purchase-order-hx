"""Reports → Products & Sizes. Revenue, quantity, and mix by product and by
container size, for the current scope. Also hosts "Manage products" — the
persistent, dashboard-wide product visibility toggle (a hidden product is excluded
from every reporting surface app-wide, but Edit PO and the QuickBooks pages are
unaffected; see dashboard/data.py's hidden_products table and schema.sql)."""

import plotly.express as px
import streamlit as st

from data import PLOTLY_CONFIG, load_hidden_products, month_over_month_movers, set_product_hidden, style
from ui_kit import (
    data_grid,
    data_table,
    empty_state,
    entity_comparison,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
)

_TOP_N_BARS = 15        # "Revenue by product" — full list still goes to the CSV
_TOP_N_SERIES = 12      # "Product mix over time" — the rest collapse into "Other"


def _size_label(s) -> str:
    """Container size for display — blank / NULL becomes 'Unspecified' so it reads
    as a real bucket rather than an empty axis tick."""
    return s if isinstance(s, str) and s.strip() else "Unspecified"


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

    def _toggle(pname: str) -> None:
        # on_change fires only on a real click, never on a plain rerun — so act on
        # the widget's new value directly instead of inferring "was toggled" from
        # state equality (which reversed an out-of-band hide when hidden_products
        # changed in another session while a stale checkbox value lingered).
        set_product_hidden(pname, hidden=not st.session_state[f"pv_{pname}"])
        load_hidden_products.clear()

    cols = st.columns(3)
    for i, name in enumerate(all_names):
        cols[i % 3].checkbox(
            name, value=name not in ctx.hidden_products, key=f"pv_{name}",
            on_change=_toggle, args=(name,),
        )


def render_manage_only(ctx) -> None:
    """Just the product-visibility toggle — for the Settings & Connections wrapper,
    which shouldn't run the whole analytics page's queries/charts."""
    page_scaffold("Product visibility", "Hide a product to exclude it from every report, chart, filter, and export app-wide.")
    with section_card(
        "Manage products",
        "Persists for everyone until turned back on. Edit PO and the QuickBooks pages are unaffected.",
    ):
        _manage_products(ctx)


def render(ctx) -> None:
    f_inv_items, palette = ctx.f_inv_items, ctx.palette
    by_product_inv, product_colors = ctx.by_product_inv, ctx.product_colors

    page_scaffold("Products & Sizes", "Revenue, quantity, and mix by product and container size, for the current scope.")
    scope_bar(ctx.fs, order_count=int(ctx.f_inv["id"].nunique()), count_noun="invoices")
    if ctx.include_samples:
        st.caption("'Samples' line-type is on — sample lines are folded into the product totals below.")

    with section_card(
        "Manage products",
        "Hide a product to exclude it from every report, chart, filter, and export "
        "app-wide — persists for everyone until turned back on. Edit PO and the "
        "QuickBooks pages are unaffected.",
    ):
        _manage_products(ctx)

    if f_inv_items.empty:
        empty_state("No line items in the current filter.")
        return

    with section_card("Revenue by product"):
        ranked = by_product_inv.sort_values("revenue", ascending=False)
        top = ranked.head(_TOP_N_BARS)
        fig = px.bar(
            top.sort_values("revenue", ascending=True), x="revenue", y="product_name", orientation="h",
            color="product_name", color_discrete_map=product_colors,
            labels={"revenue": "Revenue ($)", "product_name": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, palette, height=380), use_container_width=True, config=PLOTLY_CONFIG, key="chart_revenue_by_product")
        if len(ranked) > len(top):
            st.caption(f"Top {_TOP_N_BARS} of {len(ranked)} products shown — full list in the CSV.")
        st.download_button(
            "Download product revenue (CSV)",
            ranked.rename(columns={"product_name": "Product", "revenue": "Revenue ($)", "quantity": "Quantity"})
            .to_csv(index=False).encode("utf-8"),
            file_name="revenue_by_product.csv", mime="text/csv", key="dl_products",
        )

    with section_card("Revenue & quantity by container size", "Every product line in scope, grouped by the size it was sold in."):
        by_size_src = f_inv_items.copy()
        by_size_src["size"] = by_size_src["container_size"].map(_size_label)
        by_size = by_size_src.groupby("size", as_index=False).agg(
            revenue=("line_total", "sum"), quantity=("quantity", "sum"),
        ).sort_values("revenue", ascending=False)
        fig_sz = px.bar(
            by_size.sort_values("revenue", ascending=True), x="revenue", y="size", orientation="h",
            labels={"revenue": "Revenue ($)", "size": ""},
        )
        fig_sz.update_traces(marker_color=palette["sequential_blue"][4])
        st.plotly_chart(style(fig_sz, palette, height=260), use_container_width=True, config=PLOTLY_CONFIG, key="chart_revenue_by_size")

        pxs = by_size_src.groupby(["product_name", "size"], as_index=False).agg(
            revenue=("line_total", "sum"), quantity=("quantity", "sum"),
        ).sort_values("revenue", ascending=False)
        pxs = pxs.rename(columns={"size": "container_size"})
        data_grid(
            pxs, ["product_name", "container_size", "quantity", "revenue"],
            key="prod_by_size", download_name="revenue_by_product_size.csv",
        )

    with section_card("Compare products", "Pick two or more products to compare quantity and revenue side by side."):
        product_options_all = sorted(by_product_inv["product_name"].dropna().unique().tolist())
        entity_comparison(
            f_inv_items, "product_name", "Product", product_options_all, "effective_date",
            [("Quantity", "quantity", "sum"), ("Revenue ($)", "line_total", "sum")],
            palette, key="cmp_products",
        )

    with section_card("Product mix over time", "Quantity by product per month. Click a bar for a product/customer breakdown."):
        by_month_product = f_inv_items.dropna(subset=["effective_date"]).copy()
        by_month_product["month"] = by_month_product["effective_date"].dt.to_period("M").dt.to_timestamp()
        mix = by_month_product.groupby(["month", "product_name"])["quantity"].sum().reset_index()
        if mix.empty:
            st.caption("Not enough dated line items to show product mix over time.")
        else:
            # Keep the chart legible: colour only the top-N products by total quantity,
            # roll the rest into "Other". The click-through breakdown below still uses
            # the unbucketed detail, so no product is lost.
            keep = mix.groupby("product_name")["quantity"].sum().nlargest(_TOP_N_SERIES).index
            n_other = mix["product_name"].nunique() - len(keep)
            mix_plot = mix.copy()
            mix_plot["product_name"] = mix_plot["product_name"].where(mix_plot["product_name"].isin(keep), "Other")
            mix_plot = mix_plot.groupby(["month", "product_name"], as_index=False)["quantity"].sum()
            fig3 = px.bar(
                mix_plot, x="month", y="quantity", color="product_name",
                color_discrete_map={**product_colors, "Other": palette["ink_muted"]},
                labels={"month": "", "quantity": "Quantity", "product_name": "Product"},
            )
            period_drilldown(
                fig3, "chart_product_mix_time", by_month_product, "month",
                [("Product", "product_name"), ("Customer", "customer_name")],
                {"Quantity": ("quantity", "sum"), "Revenue ($)": ("line_total", "sum")},
                palette,
            )
            if n_other > 0:
                st.caption(f"Top {_TOP_N_SERIES} products coloured; {n_other} more grouped as 'Other'. Click a bar for the real breakdown.")

    with section_card("Top movers (month over month)"):
        movers = month_over_month_movers(f_inv_items, "effective_date", "product_name", "line_total")
        if movers is None:
            st.caption("Need at least two distinct months of data in the current filter to compare.")
        else:
            mdf, curr_m, prev_m, skipped_partial = movers
            cap = f"Comparing **{curr_m}** to **{prev_m}**."
            if skipped_partial:
                cap += " The current in-progress month is excluded so it's full-month vs full-month."
            st.caption(cap)
            prev_col, curr_col = f"{prev_m} Revenue", f"{curr_m} Revenue"
            disp = mdf[["product_name", "prev", "curr", "Change"]].rename(
                columns={"product_name": "Product", "prev": prev_col, "curr": curr_col}
            )
            data_table(disp, column_config={
                prev_col: st.column_config.NumberColumn(prev_col, format="dollar"),
                curr_col: st.column_config.NumberColumn(curr_col, format="dollar"),
            })
