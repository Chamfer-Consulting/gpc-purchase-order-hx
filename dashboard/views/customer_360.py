"""
Customer 360 — the account dossier (redesign spec §05, Phase D). Pick a customer
and see, on one page: ordering cadence, product & size mix, the sizes they
typically buy and how that has shifted, how their orders change from requested to
revised to shipped, and their unit-price history. North-star = this customer's
product-sales revenue.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    color_map_for,
    customer_order_lifecycle,
    fmt_delta,
    load_matched_line_items,
    style,
    typical_sizes,
)
from ui_kit import (
    chart_frame,
    data_grid,
    empty_state,
    kpi_strip,
    metric_help,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
    state_chip,
)


def _monthly(df: pd.DataFrame, value_col: str, agg: str) -> pd.DataFrame:
    d = df.dropna(subset=["effective_date"]).copy()
    if d.empty:
        return d.assign(month=pd.NaT)
    d["month"] = d["effective_date"].dt.to_period("M").dt.to_timestamp()
    return d


def render(ctx) -> None:
    palette = ctx.palette
    by_customer_inv = ctx.by_customer_inv
    f_inv, f_inv_items = ctx.f_inv, ctx.f_inv_items
    invoices, inv_items_all, all_items, valid_po = (
        ctx.invoices, ctx.inv_items_all, ctx.all_items, ctx.valid_po,
    )

    page_scaffold(
        "Customer 360",
        "Everything about one account — ordering cadence, sizes, how orders change "
        "from request to shipment, and value.",
    )

    if by_customer_inv.empty:
        empty_state("No customers in the current scope.")
        return

    ranked = by_customer_inv.sort_values("revenue", ascending=False)
    labels = {
        f"{r.customer_name}  ·  ${r.revenue:,.0f}  ·  {int(r.invoices):,} orders": r.customer_name
        for r in ranked.itertuples()
    }
    picked_label = st.selectbox("Customer", list(labels), key="c360_pick")
    cust = labels[picked_label]
    scope_bar(ctx.fs)

    c_inv = f_inv[f_inv["customer_name"] == cust]
    c_prod = f_inv_items[(f_inv_items["customer_name"] == cust) & (f_inv_items["category"] == "product")]
    hist = invoices[invoices["customer_name"] == cust]
    matched = load_matched_line_items()
    lc = customer_order_lifecycle(cust, valid_po, matched)

    # ── KPI strip ────────────────────────────────────────────────────────────
    revenue = c_prod["line_total"].sum()
    n_orders = int(c_inv["id"].nunique())
    avg_order = revenue / n_orders if n_orders else 0
    fulfil = None
    if not lc.empty and pd.to_numeric(lc["revised_amount"], errors="coerce").sum() > 0:
        fulfil = (
            pd.to_numeric(lc["shipped_amount"], errors="coerce").sum()
            / pd.to_numeric(lc["revised_amount"], errors="coerce").sum() * 100
        )
    since = hist["effective_date"].min()

    delta_rev = None
    if ctx.prev_start is not None and ctx.prev_end is not None:
        prev = inv_items_all[
            (inv_items_all["customer_name"] == cust)
            & (inv_items_all["category"] == "product")
            & (inv_items_all["effective_date"] >= ctx.prev_start)
            & (inv_items_all["effective_date"] <= ctx.prev_end)
        ]
        if not prev.empty:
            delta_rev = revenue - prev["line_total"].sum()

    kpi_strip([
        {"label": "Revenue", "value": f"${revenue:,.0f}", "delta": fmt_delta(delta_rev, prefix="$"),
         "help": metric_help("Revenue")},
        {"label": "Orders", "value": f"{n_orders:,}"},
        {"label": "Avg order", "value": f"${avg_order:,.0f}"},
        {"label": "Fulfilment rate", "value": f"{fulfil:.1f}%" if fulfil is not None else "—",
         "help": metric_help("Fulfilment %")},
        {"label": "Customer since", "value": since.strftime("%b %Y") if pd.notna(since) else "—"},
    ], north_star=0)

    # ── ordering cadence ─────────────────────────────────────────────────────
    with section_card("Ordering cadence", "Revenue and order count by month for this customer. Click a bar to drill in."):
        cm = _monthly(c_prod, "line_total", "sum")
        if cm["month"].isna().all():
            st.caption("Not enough dated line items for this customer in the current scope.")
        else:
            rev_m = cm.groupby("month", as_index=False)["line_total"].sum()
            fig = px.bar(rev_m, x="month", y="line_total", labels={"month": "", "line_total": "Revenue ($)"})
            fig.update_traces(marker_color=palette["categorical"][0])
            period_drilldown(
                fig, "c360_cadence", cm, "month",
                [("Product", "product_name")], {"Revenue ($)": ("line_total", "sum"), "Qty": ("quantity", "sum")},
                palette,
            )
            ord_m = _monthly(c_inv, "id", "nunique")
            oc = ord_m.groupby("month", as_index=False)["id"].nunique().rename(columns={"id": "Orders"})
            fig2 = px.line(oc, x="month", y="Orders", markers=True, labels={"month": ""})
            fig2.update_traces(line_color=palette["categorical"][3])
            chart_frame(fig2, palette=palette, key="c360_orders_m", title="Orders per month", size="compact")

    # ── product & size mix ───────────────────────────────────────────────────
    with section_card("Product & size mix", "Quantity by product, split by container size."):
        if c_prod.empty:
            st.caption("No product line items for this customer in the current scope.")
        else:
            mix = c_prod.groupby(["product_name", "container_size"], as_index=False)["quantity"].sum()
            fig = px.bar(
                mix, x="product_name", y="quantity", color="container_size", barmode="stack",
                labels={"product_name": "", "quantity": "Qty", "container_size": "Size"},
            )
            chart_frame(fig, palette=palette, key="c360_mix", size="std")
            summ = c_prod.groupby("product_name", as_index=False).agg(
                quantity=("quantity", "sum"), line_total=("line_total", "sum"),
            ).sort_values("line_total", ascending=False)
            data_grid(summ, ["product_name", "quantity", "line_total"], key="c360_prodsumm")

    # ── typical sizes & shift ────────────────────────────────────────────────
    with section_card("Typical sizes & how they've shifted",
                      "The size this customer usually orders for each product, comparing the earlier "
                      "half of their history to the more recent half. Uses full history, not the date filter."):
        ts = typical_sizes(cust, inv_items_all)
        if ts.empty:
            st.caption("No sized product history for this customer.")
        else:
            ts_show = ts.rename(columns={
                "product_name": "Product", "usual_size": "Usual size",
                "early_size": "Earlier", "recent_size": "Recent", "shifted": "Shifted?",
            })
            data_grid(ts_show, list(ts_show.columns), key="c360_sizes")
            shifted = ts[ts["shifted"]]
            if not shifted.empty:
                st.caption("↕ Shifted: " + ", ".join(
                    f"{r.product_name} ({r.early_size} → {r.recent_size})" for r in shifted.itertuples()
                ))

    # ── requested → revised → shipped ────────────────────────────────────────
    with section_card("Order value: requested → revised → shipped",
                      "For orders that have a purchase order document. Requested = first version, "
                      "Revised = latest version, Shipped = matched invoice lines."):
        if lc.empty:
            st.caption("No PO-documented orders for this customer — value tracking needs a purchase order.")
        else:
            req = pd.to_numeric(lc["requested_amount"], errors="coerce").sum()
            rev = pd.to_numeric(lc["revised_amount"], errors="coerce").sum()
            shp = pd.to_numeric(lc["shipped_amount"], errors="coerce").sum()
            wf = pd.DataFrame({"Stage": ["Requested", "Revised", "Shipped"], "Amount": [req, rev, shp]})
            fig = px.bar(wf, x="Stage", y="Amount", labels={"Stage": "", "Amount": "$"})
            fig.update_traces(marker_color=[
                palette["categorical"][0], palette["categorical"][3], palette["status"]["good"],
            ])
            chart_frame(fig, palette=palette, key="c360_waterfall", size="compact")
            st.caption(
                f"Revised is {fmt_delta(rev - req, prefix='$') or '$0'} vs requested; "
                f"shipped is {fmt_delta(shp - rev, prefix='$') or '$0'} vs revised."
            )
            data_grid(
                lc, ["source_file", "effective_date", "requested_amount", "revised_amount",
                     "shipped_amount", "fulfillment_pct"],
                key="c360_lifecycle", download_name=f"{cust}_order_lifecycle.csv",
            )

    # ── unit price history ───────────────────────────────────────────────────
    with section_card("Unit price history", "Unit price paid over time for a product/size."):
        priced = all_items[
            (all_items["customer_name"] == cust) & all_items["unit_price"].notna()
            & (~all_items["is_sample"].fillna(False)) & (all_items["product_name"] != "UNKNOWN")
        ]
        if priced.empty:
            st.caption("No priced line items for this customer.")
        else:
            pc1, pc2 = st.columns(2)
            prods = sorted(priced["product_name"].dropna().unique())
            p = pc1.selectbox("Product", prods, key="c360_price_prod")
            szs = sorted(priced.loc[priced["product_name"] == p, "container_size"].dropna().unique())
            s = pc2.selectbox("Size", szs, key="c360_price_size") if szs else None
            series = priced[(priced["product_name"] == p) & (priced["container_size"] == s)].sort_values("effective_date")
            if series.empty:
                st.caption("No priced history for that product/size.")
            else:
                fig = px.scatter(series, x="effective_date", y="unit_price",
                                 labels={"effective_date": "", "unit_price": "Unit price ($)"})
                fig.update_traces(mode="lines+markers", line_color=palette["categorical"][0])
                chart_frame(fig, palette=palette, key="c360_price", size="std")

    # ── the list ─────────────────────────────────────────────────────────────
    with section_card("All customers", "Click a row's customer in the picker above to switch."):
        data_grid(
            ranked, ["customer_name", "invoices", "revenue", "avg_invoice_value"],
            key="c360_all", download_name="customers.csv",
        )
