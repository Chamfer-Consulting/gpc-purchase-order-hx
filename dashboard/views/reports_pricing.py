"""
📊 Reports → Pricing & Reference Prices. Phase 2 finishes the visual merge (Phase 1 did
the mechanical file merge): a collapsible price-history section sits above the editable
reference-price table, which is the page's primary/actionable surface. Every widget key
and the Reference Prices save-diff-against-snapshot logic are unchanged from Phase 1.
"""

import plotly.express as px
import streamlit as st

from data import color_map_for, load_reference_prices, save_reference_prices, style
from ui_kit import data_table, page_scaffold, scope_bar


def render(ctx) -> None:
    page_scaffold(
        "Pricing & Reference Prices",
        "Review price history and drift, then set the reference prices that drive the "
        "💲 Price anomaly flag on new orders.",
    )
    scope_bar(ctx.fs)
    with st.expander("📈 Price history", expanded=True):
        _render_price_history(ctx)
    st.divider()
    _render_reference_prices(ctx)


def _render_price_history(ctx) -> None:
    all_items, f_po, palette = ctx.all_items, ctx.f_po, ctx.palette

    st.caption(
        "Unit price paid over time per customer, for a selected product/size — see the "
        "pre/post-2024-06-01 pricing standardization and any ongoing drift. Respects the "
        "sidebar filters above."
    )
    # Product/size options come from ALL priced history (not the sidebar date filter),
    # so the selectors stay stable across filter changes — only the plotted series below
    # is scoped to the current filter. Keeps the widgets' `key`-bound state valid across
    # reruns instead of the option list shrinking out from under a prior selection.
    priced_all = all_items[
        (~all_items["is_sample"].fillna(False)) & all_items["unit_price"].notna()
        & (all_items["product_name"] != "UNKNOWN")
        & (~all_items["product_name"].isin(ctx.hidden_products))
    ]

    if priced_all.empty:
        st.info("No priced line items in the data yet.")
        return

    pc1, pc2 = st.columns(2)
    products = sorted(priced_all["product_name"].dropna().unique())
    prod_choice = pc1.selectbox("Product", products, key="pricing_product")
    sizes = sorted(priced_all.loc[priced_all["product_name"] == prod_choice, "container_size"].dropna().unique())
    size_choice = pc2.selectbox("Size", sizes, key="pricing_size")

    series = priced_all[
        priced_all["po_id"].isin(f_po["id"])
        & (priced_all["product_name"] == prod_choice) & (priced_all["container_size"] == size_choice)
    ].sort_values("effective_date")

    if series.empty:
        st.info("No priced history for this product/size in the current filter.")
        return

    cust_colors = color_map_for(series["customer_name"].dropna().unique().tolist(), palette)
    fig_price = px.scatter(
        series, x="effective_date", y="unit_price", color="customer_name",
        color_discrete_map=cust_colors,
        labels={"effective_date": "", "unit_price": "Unit Price ($)", "customer_name": "Customer"},
    )
    fig_price.update_traces(mode="lines+markers")
    fig_price.add_shape(
        type="line", x0="2024-06-01", x1="2024-06-01", y0=0, y1=1, yref="paper",
        line=dict(dash="dash", color=palette["ink_muted"]),
    )
    fig_price.add_annotation(
        x="2024-06-01", y=1, yref="paper", showarrow=False, yanchor="bottom",
        text="Pricing standardized", font=dict(color=palette["ink_muted"], size=10),
    )
    st.plotly_chart(style(fig_price, palette, height=360), use_container_width=True, key="chart_pricing_history")

    ref_prices_df = load_reference_prices()
    ref_for_selection = ref_prices_df[
        (ref_prices_df["product_name"] == prod_choice) & (ref_prices_df["container_size"] == size_choice)
    ]
    if not ref_for_selection.empty:
        st.caption(f"Current reference price for **{prod_choice} ({size_choice})**, per customer:")
        data_table(
            ref_for_selection[["customer_name", "price", "source"]].rename(columns={
                "customer_name": "Customer", "price": "Reference Price ($)", "source": "Source",
            }),
        )
    st.caption("Manage/override any reference price in the table below.")


def _render_reference_prices(ctx) -> None:
    st.subheader("🏷️ Reference prices")
    st.caption(
        "Expected/current price per customer, product, and size — the basis for the "
        "💲 Price anomalies flag in Data Quality. **auto** rows refresh "
        "automatically from the most recent price actually paid each time new POs are "
        "extracted; edit a price or add a row below to set a permanent manual override — "
        "overrides are never touched by future refreshes."
    )
    ref_df = load_reference_prices()
    editor_seed = ref_df[["customer_name", "product_name", "container_size", "price", "source"]].copy()
    edited_prices = st.data_editor(
        editor_seed, num_rows="dynamic", use_container_width=True, key="reference_prices_editor",
        column_config={
            "customer_name": st.column_config.TextColumn("Customer"),
            "product_name": st.column_config.TextColumn("Product"),
            "container_size": st.column_config.TextColumn("Size"),
            "price": st.column_config.NumberColumn("Price ($)", format="%.2f"),
            "source": st.column_config.TextColumn("Source", disabled=True),
        },
    )

    if st.button("💾 Save changes", key="save_reference_prices"):
        seed_key_price = {
            (r["customer_name"], r["product_name"], r["container_size"]): r["price"]
            for r in editor_seed.to_dict("records")
        }
        rows = []
        for r in edited_prices.to_dict("records"):
            cust, prod, size, price = r.get("customer_name"), r.get("product_name"), r.get("container_size"), r.get("price")
            if not (cust and prod and size) or price is None:
                continue
            key = (cust, prod, size)
            if key in seed_key_price and float(seed_key_price[key]) == float(price):
                continue  # unchanged — leave alone so it can still auto-refresh later
            rows.append({"customer_name": cust, "product_name": prod, "container_size": size, "price": price})
        if rows:
            save_reference_prices(rows)
            load_reference_prices.clear()
            st.success(f"Saved {len(rows)} changed/added reference price(s).")
            st.rerun()
        else:
            st.info("No changes to save.")
