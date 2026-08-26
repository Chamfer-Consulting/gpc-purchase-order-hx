"""
📦 Fulfillment → Requested vs Delivered. Phase 3 polish: Fulfillment % renders as an
in-cell progress bar, $ / Qty Variance get conditional coloring (via the app's own
validated status palette, not raw red/green), and the period picker is a
segmented_control like Breakdown's. Relocated from its former home under "📊 Reports"
in Phase 1 — all underlying computations are unchanged.
"""

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

from data import color_map_for, get_database_url, load_matched_line_items, style
from ui_kit import (
    data_table,
    empty_state,
    kpi_strip,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
)


def _variance_styler(palette):
    good, serious = palette["status"]["good"], palette["status"]["serious"]

    def _color(val):
        if pd.isna(val) or val == 0:
            return ""
        return f"background-color: {good}30" if val > 0 else f"background-color: {serious}30"

    return _color


def render(ctx) -> None:
    """Standalone page (kept working, but nav now points at Order Lifecycle, which
    calls detailed_sections() below after its own aggregate view)."""
    page_scaffold(
        "Requested vs Delivered",
        "PO line items (requested) vs. matched QuickBooks invoice line items "
        "(delivered), for the current scope.",
    )
    scope_bar(ctx.fs, order_count=int(ctx.f_po["id"].nunique()))
    detailed_sections(ctx)


def detailed_sections(ctx) -> None:
    """Everything below the page header: the compare, the multi-dimensional
    breakdown pivot, the matched PO<->invoice detail, and delivery/donation
    charges. Called by both render() and views/order_lifecycle.py."""
    f_po, palette = ctx.f_po, ctx.palette

    with section_card(
        "🆚 Compare customers' fulfillment",
        "Pick two or more customers to compare requested vs. delivered amounts and fulfillment rate.",
    ):
        po_ids_all = f_po["id"].tolist()
        matched_all = load_matched_line_items()
        fulfillment_detail = matched_all[
            matched_all["po_id"].isin(po_ids_all) & (~matched_all["product_name"].isin(ctx.hidden_products))
        ]
        cust_options = sorted(fulfillment_detail["customer_name"].dropna().unique().tolist())
        picked = st.multiselect("Compare customers", cust_options, default=[], key="cmp_fulfillment_pick")
        if len(picked) < 2:
            st.caption("Pick 2 or more customers above to compare.")
        else:
            subset = fulfillment_detail[fulfillment_detail["customer_name"].isin(picked)]
            summary = subset.groupby("customer_name", as_index=False).agg(
                requested_amount=("requested_amount", "sum"), delivered_amount=("delivered_amount", "sum"),
            )
            summary["Fulfillment %"] = summary.apply(
                lambda r: round(r["delivered_amount"] / r["requested_amount"] * 100, 1) if r["requested_amount"] else None,
                axis=1,
            )
            display = summary.rename(columns={
                "customer_name": "Customer", "requested_amount": "Requested ($)", "delivered_amount": "Delivered ($)",
            })
            data_table(display, column_config={
                "Fulfillment %": st.column_config.ProgressColumn("Fulfillment %", format="%.1f%%", min_value=0, max_value=100),
            })

            chart_long = summary.melt(
                id_vars=["customer_name"], value_vars=["requested_amount", "delivered_amount"],
                var_name="Type", value_name="Amount",
            )
            chart_long["Type"] = chart_long["Type"].map({"requested_amount": "Requested", "delivered_amount": "Delivered"})
            fig_cmp = px.bar(
                chart_long, x="customer_name", y="Amount", color="Type", barmode="group",
                color_discrete_map={"Requested": palette["categorical"][0], "Delivered": palette["categorical"][1]},
                labels={"customer_name": "", "Amount": "$"},
            )
            st.plotly_chart(style(fig_cmp, palette, height=340), use_container_width=True, key="chart_cmp_fulfillment")

    with section_card("Detailed breakdown", "Complete detail — slice by time period, customer, product, and size, in any combination."):
        bc1, bc2 = st.columns(2)
        period_choice = bc1.segmented_control(
            "Time period", ["All time", "Day", "Week", "Month", "Quarter", "Year"],
            default="Month", key="breakdown_period_sc",
        ) or "Month"
        dims = bc2.multiselect(
            "Break down by", ["Customer", "Product", "Size"], default=["Product"], key="breakdown_dims",
        )

        po_ids = f_po["id"].tolist()
        if not po_ids:
            st.info("No orders in the current filter.")
        else:
            matched_items = load_matched_line_items()
            detail = matched_items[
                matched_items["po_id"].isin(po_ids) & (~matched_items["product_name"].isin(ctx.hidden_products))
            ].copy()

            if detail.empty:
                st.info("No confirmed matches with line-item detail in the current filter.")
            else:
                period_freq = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}
                group_cols = []
                if period_choice != "All time":
                    detail["Period"] = detail["effective_date"].dt.to_period(period_freq[period_choice]).dt.start_time
                    group_cols.append("Period")
                dim_col_map = {"Customer": "customer_name", "Product": "product_name", "Size": "container_size"}
                group_cols += [dim_col_map[d] for d in dims]

                if not group_cols:
                    detail["All"] = "All"
                    group_cols = ["All"]

                grouped = detail.groupby(group_cols, as_index=False).agg(
                    requested_qty=("requested_qty", "sum"), requested_amount=("requested_amount", "sum"),
                    delivered_qty=("delivered_qty", "sum"), delivered_amount=("delivered_amount", "sum"),
                    po_math_notes=("po_math_note", lambda s: "; ".join(sorted(set(x for x in s if isinstance(x, str) and x)))[:200]),
                )
                grouped["Qty Variance"] = grouped["delivered_qty"] - grouped["requested_qty"]
                grouped["$ Variance"] = grouped["delivered_amount"] - grouped["requested_amount"]
                grouped["Fulfillment %"] = grouped.apply(
                    lambda r: round(r["delivered_amount"] / r["requested_amount"] * 100, 1)
                    if r["requested_amount"] else None,
                    axis=1,
                )
                # Biggest shortages first, always — regardless of period grouping. This is
                # the whole point of the report (surfacing customers we've shorted), so it
                # shouldn't take switching "Time period" to "All time" to see it; a chronological
                # view is one click away via the CSV export or the trend chart below.
                grouped = grouped.sort_values("$ Variance")

                display_df = grouped.rename(columns={
                    "customer_name": "Customer", "product_name": "Product", "container_size": "Size",
                    "requested_qty": "Requested Qty", "requested_amount": "Requested ($)",
                    "delivered_qty": "Delivered Qty", "delivered_amount": "Delivered ($)",
                    "po_math_notes": "PO Math Note",
                })
                if "All" in display_df.columns:
                    display_df = display_df.drop(columns=["All"])

                shorted = grouped[grouped["$ Variance"] < 0]
                kpi_strip([
                    {"label": "🔻 Total shortfall", "value": f"${shorted['$ Variance'].sum():,.0f}" if not shorted.empty else "$0"},
                    {"label": "Rows shorted", "value": f"{len(shorted):,} of {len(grouped):,}"},
                    {"label": "Worst single shortage", "value": f"${shorted['$ Variance'].min():,.0f}" if not shorted.empty else "—"},
                ], north_star=0)

                styled = display_df.style.map(_variance_styler(palette), subset=["Qty Variance", "$ Variance"])
                data_table(
                    styled,
                    column_config={
                        "Fulfillment %": st.column_config.ProgressColumn(
                            "Fulfillment %", format="%.1f%%", min_value=0, max_value=100,
                        ),
                    },
                )
                st.caption(
                    "**PO Math Note** flags a known arithmetic quirk on the PO side (e.g. a "
                    "per-unit surcharge baked into the printed total) — a $ Variance next to a "
                    "note is a documented pricing quirk, not necessarily a fulfillment shortfall."
                )
                st.download_button(
                    "⬇️ Download breakdown (CSV)",
                    display_df.to_csv(index=False).encode("utf-8"),
                    file_name="requested_vs_delivered_breakdown.csv", mime="text/csv", key="dl_breakdown",
                )

                if period_choice != "All time":
                    show_by_customer = "Customer" in dims
                    trend_group_cols = ["Period"] + (["customer_name"] if show_by_customer else [])

                    st.subheader("📈 Requested vs. delivered trend")
                    chart_src = detail.groupby(trend_group_cols, as_index=False).agg(
                        requested_amount=("requested_amount", "sum"), delivered_amount=("delivered_amount", "sum"),
                    )
                    chart_long = chart_src.melt(
                        id_vars=trend_group_cols, value_vars=["requested_amount", "delivered_amount"],
                        var_name="Type", value_name="Amount",
                    )
                    chart_long["Type"] = chart_long["Type"].map({
                        "requested_amount": "Requested", "delivered_amount": "Delivered",
                    })
                    if show_by_customer:
                        cust_colors = color_map_for(chart_long["customer_name"].dropna().unique().tolist(), palette)
                        fig_bd = px.line(
                            chart_long, x="Period", y="Amount", color="customer_name", line_dash="Type",
                            color_discrete_map=cust_colors, markers=True,
                            labels={"Period": "", "Amount": "Revenue ($)", "customer_name": "Customer"},
                        )
                    else:
                        fig_bd = px.line(
                            chart_long, x="Period", y="Amount", color="Type", markers=True,
                            color_discrete_map={"Requested": palette["categorical"][0], "Delivered": palette["categorical"][1]},
                            labels={"Period": "", "Amount": "Revenue ($)"},
                        )
                    period_drilldown(
                        fig_bd, "chart_breakdown_period", detail, "Period",
                        [("Customer", "customer_name"), ("Product", "product_name"), ("Size", "container_size")],
                        {"Requested ($)": ("requested_amount", "sum"), "Delivered ($)": ("delivered_amount", "sum")},
                        palette,
                    )
                    st.caption(
                        "Chart aggregates across product/size even when selected above — see the table for "
                        "the full multi-dimensional detail."
                        + (" One line per customer; dashed = Delivered, solid = Requested." if show_by_customer else "")
                    )

                    st.subheader("📅 Ordering trends")
                    st.caption(
                        "Number of purchase orders placed per period, per the sidebar filters — reflects "
                        "every order in the filter, not just ones with a confirmed QuickBooks match."
                    )
                    order_src = f_po.dropna(subset=["effective_date"]).copy()
                    order_src["Period"] = order_src["effective_date"].dt.to_period(period_freq[period_choice]).dt.start_time
                    order_group_cols = ["Period"] + (["customer_name"] if show_by_customer else [])
                    order_counts = (
                        order_src.groupby(order_group_cols, as_index=False)["id"].nunique()
                        .rename(columns={"id": "Orders"})
                    )
                    if show_by_customer:
                        fig_orders = px.line(
                            order_counts, x="Period", y="Orders", color="customer_name", markers=True,
                            color_discrete_map=color_map_for(order_counts["customer_name"].dropna().unique().tolist(), palette),
                            labels={"Period": "", "customer_name": "Customer"},
                        )
                    else:
                        fig_orders = px.line(order_counts, x="Period", y="Orders", markers=True, labels={"Period": ""})
                        fig_orders.update_traces(line_color=palette["categorical"][0])
                    period_drilldown(
                        fig_orders, "chart_order_trend", order_src, "Period",
                        [("Customer", "customer_name")], {"Orders": ("id", "nunique")}, palette,
                    )

            with section_card("Matched PO ↔ Invoice detail"):
                rvd_conn = psycopg2.connect(get_database_url())
                try:
                    with rvd_conn.cursor() as cur:
                        cur.execute(
                            "SELECT po.po_number, po.source_file, po.customer_name, po.total, "
                            "inv.doc_number, inv.txn_date, inv.total_amt, l.match_method "
                            "FROM po_invoice_links l "
                            "JOIN purchase_orders po ON po.id = l.po_id "
                            "JOIN qbo_invoices inv ON inv.id = l.invoice_id "
                            "WHERE l.confirmed = TRUE AND l.po_id = ANY(%s) "
                            "ORDER BY po.po_number",
                            (po_ids,),
                        )
                        cols = [d[0] for d in cur.description]
                        detail_rows = cur.fetchall()
                finally:
                    rvd_conn.close()
                if not detail_rows:
                    st.caption("No confirmed matches in the current filter yet.")
                else:
                    detail_df = pd.DataFrame(detail_rows, columns=cols)
                    detail_df["variance"] = detail_df["total_amt"].astype(float) - detail_df["total"].astype(float)
                    data_table(
                        detail_df.rename(columns={
                            "po_number": "PO Number", "source_file": "Source File", "customer_name": "Customer",
                            "total": "PO Total ($)", "doc_number": "Invoice #", "txn_date": "Invoice Date",
                            "total_amt": "Invoice Total ($)", "match_method": "Match Method", "variance": "Variance ($)",
                        }),
                    )

            with section_card("🚚 Delivery & donation charges by customer",
                               "QuickBooks Delivery/Donation line items, attributed to whichever PO their "
                               "containing invoice is confirmed-linked to. Only invoices confirmed-linked "
                               "in the current filter appear here."):
                dd_conn = psycopg2.connect(get_database_url())
                try:
                    dd_rows = pd.read_sql_query(
                        "SELECT po.customer_name, po.po_number, po.source_file, ii.category, "
                        "SUM(ii.line_total) AS total, COUNT(*) AS n_lines "
                        "FROM po_invoice_links l "
                        "JOIN purchase_orders po ON po.id = l.po_id "
                        "JOIN qbo_invoice_items ii ON ii.invoice_id = l.invoice_id "
                        "WHERE l.confirmed = TRUE AND l.po_id = ANY(%(ids)s) "
                        "AND ii.category IN ('delivery', 'donation') "
                        "GROUP BY po.customer_name, po.po_number, po.source_file, ii.category "
                        "ORDER BY po.customer_name, po.po_number",
                        dd_conn, params={"ids": po_ids},
                    )
                finally:
                    dd_conn.close()

                if dd_rows.empty:
                    st.caption("No delivery or donation charges on confirmed-linked invoices in the current filter.")
                else:
                    data_table(
                        dd_rows.rename(columns={
                            "customer_name": "Customer", "po_number": "PO Number", "source_file": "Source File",
                            "category": "Type", "total": "Total ($)", "n_lines": "# Lines",
                        }),
                    )
                    st.download_button(
                        "⬇️ Download delivery & donation charges (CSV)",
                        dd_rows.to_csv(index=False).encode("utf-8"),
                        file_name="delivery_donation_by_po.csv", mime="text/csv", key="dl_delivery_donation",
                    )
