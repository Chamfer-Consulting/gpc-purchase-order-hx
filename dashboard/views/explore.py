"""
Explore — the one slice-and-dice surface (redesign spec §05). Replaces the former
Trends + Breakdown + Compare-periods pages: a measure × grain × break-by pivot with
a drill-down chart and a table, then the year-over-year and two-period comparison
panels that used to live on Trends.

Saved views (spec decision #5) are Phase F — the control state already lives in
st.session_state under stable keys, ready to be snapshotted.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    color_map_for,
    compare_periods_by_group,
    delete_view,
    fmt_delta,
    load_saved_views,
    save_view,
    style,
    yoy_annual_chart,
)
from ui_kit import (
    data_grid,
    empty_state,
    kpi_strip,
    page_scaffold,
    period_drilldown,
    scope_bar,
    section_card,
    yoy_drilldown,
)

_GRAIN_FREQ = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}
_VIEW_KEYS = {"xp_measure": "measure", "xp_grain": "grain", "xp_dims": "dims", "xp_chart": "chart"}
_TOP_N_SERIES = 12   # colour cap on the pivot chart; the rest roll into "Other"


def _saved_views_bar() -> None:
    """Load / save / delete named Explore configurations (spec decision #5). Must
    render before the control widgets so a load can set their session_state."""
    views = load_saved_views("explore")
    with st.container(horizontal=True):
        for v in views:
            if st.button(v["name"], key=f"xp_load_{v['name']}"):
                for skey, ckey in _VIEW_KEYS.items():
                    if ckey in (v["config"] or {}):
                        st.session_state[skey] = v["config"][ckey]
                st.rerun()
        with st.popover("＋ Save view"):
            name = st.text_input("Name for this view", key="xp_save_name")
            if st.button("Save", key="xp_save_btn") and name.strip():
                save_view("explore", name.strip(), {
                    "measure": st.session_state.get("xp_measure", "Revenue"),
                    "grain": st.session_state.get("xp_grain", "Month"),
                    "dims": st.session_state.get("xp_dims", ["Customer"]),
                    "chart": st.session_state.get("xp_chart", "Line"),
                })
                load_saved_views.clear()
                st.rerun()
        if views:
            with st.popover("Manage"):
                target = st.selectbox("Delete a saved view", [v["name"] for v in views], key="xp_del_pick")
                if st.button("Delete", key="xp_del_btn"):
                    delete_view(target)
                    load_saved_views.clear()
                    st.rerun()
_DIM_COL = {"Customer": "customer_name", "Product": "product_name", "Size": "container_size"}
_MEASURE = {
    "Revenue": ("line_total", "sum", "Revenue ($)"),
    "Orders": ("invoice_id", "nunique", "Orders"),
    "Quantity": ("quantity", "sum", "Quantity"),
}


def render(ctx) -> None:
    f_inv_items, f_inv, palette = ctx.f_inv_items, ctx.f_inv, ctx.palette

    page_scaffold(
        "Explore",
        "Build any view: pick a measure, a time grain, and how to break it down. "
        "The full QuickBooks invoice history, for the current scope.",
    )
    scope_bar(ctx.fs, order_count=int(f_inv["id"].nunique()), count_noun="invoices")

    if f_inv_items.empty:
        empty_state("No line items in the current scope.")
        return

    _saved_views_bar()

    # ── controls ─────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1.4, 2, 2])
    measure = c1.segmented_control(
        "Measure", list(_MEASURE), default="Revenue", key="xp_measure", selection_mode="single",
    ) or "Revenue"
    grain = c2.segmented_control(
        "Time grain", ["Day", "Week", "Month", "Quarter", "Year", "All time"],
        default="Month", key="xp_grain", selection_mode="single",
    ) or "Month"
    dims = c3.multiselect("Break down by", list(_DIM_COL), default=["Customer"], key="xp_dims")
    chart_kind = st.segmented_control(
        "Chart", ["Line", "Bar", "Stacked bar"], default="Line", key="xp_chart", selection_mode="single",
    ) or "Line"

    val_col, agg, val_label = _MEASURE[measure]
    detail = f_inv_items.dropna(subset=["effective_date"]).copy()

    group_cols: list[str] = []
    if grain != "All time":
        detail["Period"] = detail["effective_date"].dt.to_period(_GRAIN_FREQ[grain]).dt.start_time
        group_cols.append("Period")
    group_cols += [_DIM_COL[d] for d in dims]
    if not group_cols:
        detail["All"] = "All"
        group_cols = ["All"]

    grouped = detail.groupby(group_cols, as_index=False).agg(**{val_label: (val_col, agg)})
    grouped = (
        grouped.sort_values("Period") if "Period" in group_cols
        else grouped.sort_values(val_label, ascending=False)
    )

    # ── KPI: totals for the current build ────────────────────────────────────
    total = detail[val_col].nunique() if agg == "nunique" else detail[val_col].sum()
    kpi_strip([
        {"label": f"Total {measure.lower()}", "value": f"${total:,.0f}" if measure == "Revenue" else f"{total:,.0f}"},
        {"label": "Rows in view", "value": f"{len(grouped):,}"},
        {"label": "Grain", "value": grain},
        {"label": "Broken down by", "value": ", ".join(dims) or "—"},
    ], north_star=0)
    if measure == "Orders":
        st.caption(
            f"Counts invoices with at least one line matching the current scope ({total:,}). "
            "The Overview page's **Invoices** KPI counts every invoice, including "
            "services-only and donation-only ones with no product line."
        )
        if any(d in ("Product", "Size") for d in dims):
            st.caption(
                "Broken down by product/size, an invoice is counted once in **every** cell it "
                "has a line in — so the table's order counts sum to more than the Total orders above."
            )

    # ── chart ────────────────────────────────────────────────────────────────
    with section_card(f"{measure} by {grain.lower()}"):
        if "Period" not in group_cols:
            st.caption("Pick a time grain other than **All time** to chart this over time — see the table below for the flat totals.")
        else:
            color_dim = _DIM_COL[dims[0]] if dims else None
            n_other = 0
            detail_plot = detail
            if color_dim is not None:
                # Cap the number of coloured series so a break-down by Customer (~70)
                # or Product isn't an unreadable wall. Bucket at the row level (not
                # after aggregating) so an "Orders" (nunique) measure stays correct.
                by_series = (
                    detail.groupby(color_dim)[val_col].nunique() if agg == "nunique"
                    else detail.groupby(color_dim)[val_col].agg(agg)
                )
                keep = by_series.abs().nlargest(_TOP_N_SERIES).index
                n_other = detail[color_dim].dropna().nunique() - len(keep)
                if n_other > 0:
                    detail_plot = detail.assign(
                        **{color_dim: detail[color_dim].where(detail[color_dim].isin(keep), "Other")}
                    )
            plot = detail_plot.groupby(
                ["Period"] + ([color_dim] if color_dim else []), as_index=False,
            ).agg(**{val_label: (val_col, agg)})
            colors = color_map_for(plot[color_dim].dropna().unique().tolist(), palette) if color_dim else None
            if colors is not None:
                colors["Other"] = palette["ink_muted"]
            common = dict(x="Period", y=val_label, labels={"Period": "", val_label: val_label})
            if chart_kind == "Line":
                fig = px.line(plot, markers=True, color=color_dim, color_discrete_map=colors, **common)
            else:
                fig = px.bar(
                    plot, color=color_dim, color_discrete_map=colors,
                    barmode="stack" if chart_kind == "Stacked bar" else "group", **common,
                )
                if not color_dim:
                    fig.update_traces(marker_color=palette["categorical"][0])
            period_drilldown(
                fig, "xp_chart_render", detail, "Period",
                [(d, _DIM_COL[d]) for d in dims] or [("Customer", "customer_name")],
                {val_label: (val_col, agg)}, palette,
            )
            if n_other > 0:
                st.caption(f"Top {_TOP_N_SERIES} {dims[0].lower()}s coloured; {n_other} more grouped as 'Other'. "
                           "Click a point for the full breakdown.")

    # ── table ────────────────────────────────────────────────────────────────
    with section_card("Result table"):
        show = grouped.drop(columns=["All"], errors="ignore")
        data_grid(show, list(show.columns), key="explore", download_name="explore.csv")

    # ── year over year ───────────────────────────────────────────────────────
    with section_card(
        f"Year over year — {measure.lower()}",
        "Each calendar year as its own line, by month, for the measure selected above. "
        "Click a point for a customer breakdown.",
    ):
        current_year = str(pd.Timestamp.now().year)
        fig_yoy = yoy_annual_chart(
            detail, "effective_date", val_col, agg, val_label, palette, current_year,
        )
        if fig_yoy is None:
            st.caption("Not enough dated line items in the current scope.")
        else:
            yoy_drilldown(
                fig_yoy, "xp_yoy", detail, "effective_date",
                [("Customer", "customer_name")], {val_label: (val_col, agg)}, palette,
            )

    # ── compare two periods ──────────────────────────────────────────────────
    with section_card("Compare two periods", "Pick any two date ranges to compare side by side."):
        dmin, dmax = f_inv["effective_date"].min(), f_inv["effective_date"].max()
        if pd.isna(dmin) or pd.isna(dmax):
            st.caption("Not enough dated invoices to compare periods.")
            return
        _lo, _hi = dmin.date(), dmax.date()

        def _clamp(d):
            return min(max(d, _lo), _hi)

        pc1, pc2 = st.columns(2)
        range_a = pc1.date_input(
            "Period A", value=(_clamp((dmax - pd.Timedelta(days=29)).date()), _hi),
            min_value=_lo, max_value=_hi, key="xp_cmp_a",
        )
        range_b = pc2.date_input(
            "Period B",
            value=(_clamp((dmax - pd.Timedelta(days=59)).date()), _clamp((dmax - pd.Timedelta(days=30)).date())),
            min_value=_lo, max_value=_hi, key="xp_cmp_b",
        )
        if not (isinstance(range_a, tuple) and len(range_a) == 2 and isinstance(range_b, tuple) and len(range_b) == 2):
            st.caption("Pick a full start/end range for both periods.")
            return
        a0, a1 = pd.Timestamp(range_a[0]), pd.Timestamp(range_a[1])
        b0, b1 = pd.Timestamp(range_b[0]), pd.Timestamp(range_b[1])
        inv_a = f_inv[(f_inv["effective_date"] >= a0) & (f_inv["effective_date"] <= a1)]
        inv_b = f_inv[(f_inv["effective_date"] >= b0) & (f_inv["effective_date"] <= b1)]
        n_a, n_b = inv_a["id"].nunique(), inv_b["id"].nunique()
        # Revenue = product-line revenue (same basis as the "Total revenue" KPI above),
        # not gross invoice total_amt.
        li = f_inv_items.dropna(subset=["effective_date"])
        rev_a = li.loc[(li["effective_date"] >= a0) & (li["effective_date"] <= a1), "line_total"].sum()
        rev_b = li.loc[(li["effective_date"] >= b0) & (li["effective_date"] <= b1), "line_total"].sum()
        kpi_strip([
            {"label": "Invoices — A", "value": f"{n_a:,}"},
            {"label": "Invoices — B", "value": f"{n_b:,}", "delta": fmt_delta(n_b - n_a)},
            {"label": "Revenue — A", "value": f"${rev_a:,.0f}"},
            {"label": "Revenue — B", "value": f"${rev_b:,.0f}", "delta": fmt_delta(rev_b - rev_a, prefix="$")},
        ], north_star=None)
        movers = compare_periods_by_group(
            f_inv_items, "effective_date", "customer_name", "line_total", (a0, a1), (b0, b1)
        )
        if movers is not None and not movers.empty:
            st.caption("Customers with the biggest revenue change from A to B:")
            data_grid(
                movers, ["customer_name", "period_a", "period_b", "delta"],
                key="xp_movers", download_name="period_compare.csv",
            )
