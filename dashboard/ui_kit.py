"""
Shared visual/component vocabulary for dashboard/views/*.py pages — built once here so
every page stops being visually ad hoc (see Phase 1 of
/Users/jcaternolo/.claude/plans/golden-soaring-robin.md). Composes on top of
dashboard/data.py's palette/style()/color_map_for() etc.; does not replace them.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import color_map_for, style

# Maps this app's validated status semantics (see dashboard/data.py's LIGHT/DARK
# palette["status"]) onto st.badge's fixed color enum.
_SEVERITY_TO_BADGE_COLOR = {
    "critical": "red",
    "serious": "orange",
    "warning": "yellow",
    "good": "green",
    "info": "blue",
}

_SEVERITY_ICON = {
    "critical": "🔴",
    "serious": "🟠",
    "warning": "🟡",
    "good": "🟢",
    "info": "🔵",
}


def page_header(title: str, subtitle: str | None = None, actions=None) -> None:
    """Consistent page top: title, one-line context caption, optional right-aligned
    action buttons (export/refresh/etc — pass a callable that renders into a
    st.container, e.g. `actions=lambda: st.button("Refresh")`)."""
    if actions is not None:
        head = st.container(horizontal=True, horizontal_alignment="right")
        with head:
            st.title(title)
        with head:
            actions()
    else:
        st.title(title)
    if subtitle:
        st.caption(subtitle)


def kpi_row(items: list[dict]) -> None:
    """Renders a row of st.metric tiles in bordered columns.

    Each item: {"label": str, "value": str, "delta": str|None (optional),
    "chart_data": Sequence|None (optional, trailing sparkline),
    "chart_type": "line"|"bar"|"area" (optional, default "line")}.
    """
    if not items:
        return
    cols = st.columns(len(items), border=True)
    for col, item in zip(cols, items):
        kwargs = {}
        if item.get("chart_data") is not None:
            kwargs["chart_data"] = item["chart_data"]
            kwargs["chart_type"] = item.get("chart_type", "line")
        col.metric(item["label"], item["value"], delta=item.get("delta"), **kwargs)


def section_card(title: str | None = None, caption: str | None = None):
    """Returns a bordered st.container to `with` around one logical section (a chart,
    a table, a form) — every section gets a visible boundary instead of floating on
    bare page background. Renders the optional title/caption inside the card."""
    card = st.container(border=True)
    if title:
        card.subheader(title)
    if caption:
        card.caption(caption)
    return card


def severity_badge(level: str, label: str | None = None) -> None:
    """Renders a colored badge for one of this app's severity levels
    (critical/serious/warning/good/info), using the icon+color convention shared
    with the Home 'Needs attention' digest and the Data Quality page."""
    color = _SEVERITY_TO_BADGE_COLOR.get(level, "gray")
    icon = _SEVERITY_ICON.get(level, "⚪")
    st.badge(label or level.capitalize(), icon=icon, color=color)


def confidence_badge(confidence_text: str) -> None:
    """Renders qbo_matcher.confidence_label()'s output as a badge, colored by the
    tier keyword it contains. Domain scoring logic stays in qbo_matcher.py — this
    only maps its output string to a color."""
    text = confidence_text.lower()
    if "certain" in text:
        color, icon = "green", "✅"
    elif "high" in text:
        color, icon = "blue", "🔵"
    elif "medium" in text:
        color, icon = "yellow", "🟡"
    elif "low" in text or "verify" in text:
        color, icon = "orange", "🟠"
    else:
        color, icon = "gray", "⚪"
    st.badge(confidence_text, icon=icon, color=color)


def empty_state(message: str, tone: str = "info", cta_label: str | None = None, on_cta=None) -> None:
    """Standardized empty-data message, optionally with a callback button (e.g. a
    'Clear filters' CTA — pass `on_cta=clear_filters` where `clear_filters` performs
    the same st.session_state.pop(...) reset as the sidebar's own Clear Filters
    button, not a second copy of that key list)."""
    with st.container(border=True):
        renderer = {"info": st.info, "warning": st.warning, "error": st.error}.get(tone, st.info)
        renderer(message)
        if cta_label and on_cta is not None:
            if st.button(cta_label):
                on_cta()


def data_table(df, column_config=None, hide_index: bool = True, height=None, **kwargs) -> None:
    """Thin st.dataframe wrapper standardizing on `width="stretch"` (the modern
    replacement for the legacy `use_container_width=True`, still supported in
    streamlit==1.50.0 but deprecated)."""
    st.dataframe(
        df, width="stretch", hide_index=hide_index, column_config=column_config,
        height=height if height is not None else "auto", **kwargs,
    )


def _breakdown_table(detail_df: pd.DataFrame, mask, breakdown_dims: list[tuple[str, str]], agg_spec: dict, period_label: str) -> None:
    matched = detail_df[mask]
    if matched.empty:
        st.caption(f"No detail rows for **{period_label}**.")
        return
    group_cols = [col for _, col in breakdown_dims]
    grouped = matched.groupby(group_cols, as_index=False).agg(**agg_spec)
    grouped = grouped.rename(columns={col: label for label, col in breakdown_dims})
    sort_col = next(iter(agg_spec))
    grouped = grouped.sort_values(sort_col, ascending=False)
    st.caption(f"Breakdown for **{period_label}**:")
    data_table(grouped)


def period_drilldown(
    fig, key: str, detail_df: pd.DataFrame, period_col: str,
    breakdown_dims: list[tuple[str, str]], agg_spec: dict, palette: dict, height: int = 340,
) -> None:
    """Renders a Plotly chart where clicking a bar/point shows a breakdown table below
    for that period, grouped by breakdown_dims and aggregated per agg_spec.

    breakdown_dims: [(display_label, column_name), ...] — columns to group the
    detail_df by (e.g. [("Customer", "customer_name")]).
    agg_spec: named-aggregation kwargs for the groupby, e.g.
    {"Invoices": ("id", "nunique"), "Revenue ($)": ("total_amt", "sum")} — the table
    sorts by whichever key comes first.
    detail_df must carry a `period_col` column with values directly comparable (as
    datetimes) to the chart's own x-axis — i.e. the same already-truncated period
    column the chart was built from, not raw per-row dates.
    """
    event = st.plotly_chart(
        style(fig, palette, height=height), use_container_width=True, key=key,
        on_select="rerun", selection_mode="points",
    )
    points = (event.get("selection") or {}).get("points") or []
    if not points:
        st.caption("💡 Click a bar/point above to see its breakdown. Click it again to clear.")
        return
    clicked = pd.to_datetime(points[0]["x"])
    mask = pd.to_datetime(detail_df[period_col]) == clicked
    _breakdown_table(detail_df, mask, breakdown_dims, agg_spec, clicked.strftime("%b %d, %Y"))


def yoy_drilldown(
    fig, key: str, detail_df: pd.DataFrame, date_col: str,
    breakdown_dims: list[tuple[str, str]], agg_spec: dict, palette: dict, height: int = 340,
) -> None:
    """Like period_drilldown, but for year-over-year charts where the x-axis is
    month-of-year (1-12) shared across years and each year is a separate colored
    trace — the clicked point's trace name (the "year" value px.line's color=
    param assigns) disambiguates which year's month was actually clicked."""
    event = st.plotly_chart(
        style(fig, palette, height=height), use_container_width=True, key=key,
        on_select="rerun", selection_mode="points",
    )
    points = (event.get("selection") or {}).get("points") or []
    if not points:
        st.caption("💡 Click a point above to see its breakdown. Click it again to clear.")
        return
    point = points[0]
    curve_number = point.get("curve_number")
    if curve_number is None or curve_number >= len(fig.data) or not fig.data[curve_number].name:
        st.caption("Couldn't determine which year was clicked.")
        return
    try:
        year, moy = int(fig.data[curve_number].name), int(point["x"])
    except (TypeError, ValueError):
        st.caption("Couldn't determine which year was clicked.")
        return
    dates = pd.to_datetime(detail_df[date_col], errors="coerce")
    mask = (dates.dt.year == year) & (dates.dt.month == moy)
    label = pd.Timestamp(year=year, month=moy, day=1).strftime("%B %Y")
    _breakdown_table(detail_df, mask, breakdown_dims, agg_spec, label)


def entity_comparison(
    detail_df: pd.DataFrame, entity_col: str, entity_label: str, options: list[str],
    date_col: str, metrics: list[tuple[str, str, str]], palette: dict, key: str,
) -> None:
    """Lets the user pick 2+ entities (customers, products, ...) from `options` and
    compares them: a summary table (one row per entity, one column per metric) plus
    one overlaid monthly trend line chart per metric.

    metrics: [(display_label, source_col, agg_fn), ...] — e.g.
    [("Revenue ($)", "total_amt", "sum"), ("Invoices", "id", "nunique")].
    detail_df must carry entity_col, date_col, and every metric's source_col.
    """
    picked = st.multiselect(f"Compare {entity_label}s", options, default=[], key=f"{key}_pick")
    if len(picked) < 2:
        st.caption(f"Pick 2 or more {entity_label.lower()}s above to compare.")
        return

    subset = detail_df[detail_df[entity_col].isin(picked)]
    if subset.empty:
        st.caption("No data for the selected picks in the current filter.")
        return

    summary = subset.groupby(entity_col, as_index=False).agg(**{label: (col, agg) for label, col, agg in metrics})
    summary = summary.rename(columns={entity_col: entity_label})
    data_table(summary)

    dated = subset.dropna(subset=[date_col]).copy()
    if dated.empty:
        st.caption("No dated detail to chart.")
        return
    dated["month"] = dated[date_col].dt.to_period("M").dt.to_timestamp()
    colors = color_map_for(picked, palette)
    for label, col, agg in metrics:
        monthly = dated.groupby(["month", entity_col], as_index=False)[col].agg(agg)
        fig = px.line(
            monthly, x="month", y=col, color=entity_col, markers=True,
            color_discrete_map=colors, labels={"month": "", col: label, entity_col: entity_label},
        )
        st.plotly_chart(style(fig, palette, height=320), use_container_width=True, key=f"{key}_chart_{label}")
