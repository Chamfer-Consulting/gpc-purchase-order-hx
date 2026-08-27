"""
Order Lifecycle — the one narrative for how an order changes from what the
customer first asked for, to the final agreed PO, to what actually shipped
(redesign spec §05, Phase E). Absorbs the former Requested vs Delivered page plus
the revision analysis that used to sit inside Data Quality. North-star = fulfilment
rate (shipped $ ÷ revised $).
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import fmt_delta, load_matched_line_items, order_lifecycle
from ui_kit import (
    chart_frame,
    data_grid,
    empty_state,
    kpi_strip,
    metric_help,
    page_scaffold,
    scope_bar,
    section_card,
)
from views.fulfillment_rvd import detailed_sections


def render(ctx) -> None:
    f_po, all_items, valid_po, palette = ctx.f_po, ctx.all_items, ctx.valid_po, ctx.palette

    page_scaffold(
        "Order Lifecycle",
        "Requested → revised → shipped, per order and in aggregate — for orders that "
        "have a purchase order document, in the current scope.",
    )
    scope_bar(ctx.fs, order_count=int(f_po["id"].nunique()), count_noun="POs")

    matched = load_matched_line_items()
    lc = order_lifecycle(valid_po, f_po["po_key"], matched)
    if lc.empty:
        empty_state("No PO-documented orders in the current scope.")
        return

    req = pd.to_numeric(lc["requested_amount"], errors="coerce")
    rev = pd.to_numeric(lc["revised_amount"], errors="coerce")
    shp = pd.to_numeric(lc["shipped_amount"], errors="coerce")
    req_t, rev_t = req.sum(), rev.sum()
    # Fulfilment compares like with like: shipped $ only exists for orders with a
    # confirmed invoice match, so the denominator must be the revised $ of *those same
    # orders*, not of every in-scope order (unmatched ones would drag the rate down
    # despite nothing being known about what shipped).
    matched_mask = shp.notna()
    n_matched, n_total = int(matched_mask.sum()), len(lc)
    shp_t = shp[matched_mask].sum()
    rev_matched = rev[matched_mask].sum()
    fulfil = shp_t / rev_matched * 100 if rev_matched else None
    shortfall = (shp - rev).where(matched_mask & (shp < rev)).sum()

    kpi_strip([
        {"label": "Fulfilment rate", "value": f"{fulfil:.1f}%" if fulfil is not None else "—",
         "help": metric_help("Fulfilment %")},
        {"label": "Requested", "value": f"${req_t:,.0f}", "help": metric_help("Requested")},
        {"label": "Revised", "value": f"${rev_t:,.0f}", "delta": fmt_delta(rev_t - req_t, prefix="$"),
         "help": metric_help("Revised")},
        {"label": "Shipped", "value": f"${shp_t:,.0f}", "delta": fmt_delta(shp_t - rev_matched, prefix="$"),
         "help": metric_help("Shipped value")},
        {"label": "Total shortfall", "value": f"${abs(shortfall):,.0f}" if pd.notna(shortfall) else "$0"},
    ], north_star=0)
    st.caption(
        f"Fulfilment rate and shortfall cover the **{n_matched:,} of {n_total:,}** in-scope "
        f"orders with a confirmed invoice match; Requested and Revised cover all {n_total:,}."
    )

    # ── value by month ───────────────────────────────────────────────────────
    with section_card("Value by month", "Requested, revised and shipped totals for orders dated in each month."):
        dm = lc.dropna(subset=["effective_date"]).copy()
        if dm.empty:
            st.caption("No dated orders in the current scope.")
        else:
            dm["month"] = dm["effective_date"].dt.to_period("M").dt.to_timestamp()
            monthly = dm.groupby("month", as_index=False).agg(
                Requested=("requested_amount", "sum"), Revised=("revised_amount", "sum"),
                Shipped=("shipped_amount", "sum"),
            )
            long = monthly.melt(id_vars="month", var_name="Stage", value_name="Amount")
            fig = px.line(
                long, x="month", y="Amount", color="Stage", markers=True,
                color_discrete_map={
                    "Requested": palette["categorical"][0],
                    "Revised": palette["categorical"][3],
                    "Shipped": palette["status"]["good"],
                },
                labels={"month": "", "Amount": "$"},
            )
            chart_frame(fig, palette=palette, key="ol_monthly", size="tall")
            st.caption(
                "Shipped only covers orders with a confirmed invoice match — a gap below "
                "Revised in a given month may be unmatched orders, not a real shortfall."
            )

    # ── where the gap is ─────────────────────────────────────────────────────
    with section_card("Where the gap is", "By product and size, biggest shortfall first."):
        gap = matched[matched["po_id"].isin(f_po["id"]) & (~matched["product_name"].isin(ctx.hidden_products))]
        if gap.empty:
            st.caption("No confirmed matches with line-item detail in the current scope.")
        else:
            g = gap.groupby(["product_name", "container_size"], as_index=False).agg(
                requested_amount=("requested_amount", "sum"), delivered_amount=("delivered_amount", "sum"),
            )
            g["variance"] = g["delivered_amount"] - g["requested_amount"]
            g = g.sort_values("variance")
            fig = px.bar(
                g.head(20), x="variance", y="product_name", orientation="h", color="container_size",
                labels={"variance": "Shipped − requested ($)", "product_name": "", "container_size": "Size"},
            )
            chart_frame(fig, palette=palette, key="ol_gap", size="std")
            data_grid(
                g, ["product_name", "container_size", "requested_amount", "delivered_amount", "variance"],
                key="ol_gap_tbl", download_name="lifecycle_gap_by_product.csv",
            )

    # ── revision analysis ────────────────────────────────────────────────────
    with section_card("Revision analysis", "How the agreed PO differs from the customer's first ask."):
        # Match on po_key, not the latest version's id — ~10% of the "Added"/"Changed"
        # markers sit on a superseded version's line items and would be missed.
        changes = all_items[
            all_items["po_key"].isin(f_po["po_key"])
            & all_items["revision_status"].isin(["Added", "Changed", "Removed"])
            & (~all_items["product_name"].isin(ctx.hidden_products))
        ]
        multi = valid_po[valid_po["po_key"].isin(f_po["po_key"])].sort_values(["po_key", "effective_date", "id"])
        impacts = []
        for _, grp in multi.groupby("po_key"):
            if len(grp) >= 2 and pd.notna(grp.iloc[0]["total"]) and pd.notna(grp.iloc[-1]["total"]):
                impacts.append(grp.iloc[-1]["total"] - grp.iloc[0]["total"])
        impacts = pd.Series(impacts, dtype=float)

        kpi_strip([
            {"label": "Orders with revisions", "value": f"{len(impacts):,}"},
            {"label": "Lines added / changed / removed", "value": f"{len(changes):,}"},
            {"label": "Net $ impact of revisions", "value": f"${impacts.sum():,.0f}" if not impacts.empty else "$0"},
        ], north_star=None)

        if changes.empty:
            st.caption("No line-item changes on any order in the current scope.")
        else:
            data_grid(
                changes, ["po_number", "customer_name", "product_name", "container_size", "revision_status", "changes"],
                key="ol_changes", download_name="latest_revision_changes.csv",
            )

    # ── per-order table ──────────────────────────────────────────────────────
    with section_card("Per-order detail"):
        data_grid(
            lc, ["source_file", "customer_name", "effective_date", "requested_amount",
                 "revised_amount", "shipped_amount", "fulfillment_pct"],
            key="ol_orders", download_name="order_lifecycle.csv",
        )

    # ── the former RvD breakdown / matched detail / delivery charges ──────────
    st.divider()
    st.subheader("Detailed breakdown")
    detailed_sections(ctx)
