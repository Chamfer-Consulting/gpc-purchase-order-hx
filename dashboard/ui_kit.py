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
from labels import COLUMN_KIND, GLOSSARY
from labels import label as col_label

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
    """Back-compat alias — page_scaffold() is the canonical name (see below).
    Kept so views not yet migrated to the redesign skeleton keep working while
    still picking up the styled purpose line."""
    page_scaffold(title, subtitle, actions)


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


def section_card(title: str | None = None, caption: str | None = None, help: str | None = None):
    """Returns a bordered st.container to `with` around one logical section (a chart,
    a table, a form) — every section gets a visible boundary instead of floating on
    bare page background. Renders the optional title/caption inside the card; `help`
    adds a hover tooltip on the title (pass ui_kit.metric_help("Term"))."""
    card = st.container(border=True)
    if title:
        card.subheader(title, help=help)
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


def _nearest_period(values, target: pd.Timestamp):
    """Snaps a chart click's x-coordinate to whichever period value actually present
    in the data is closest to it. Needed because Plotly's click event for a bar trace
    on a continuous date axis reports the pixel-interpolated date under the cursor —
    wherever within the bar's rendered width the click physically landed — not the
    bar's exact category value, so a click a few pixels off-center comes back a few
    days off from the bar's real period start. Returns None if `values` is empty."""
    uniq = pd.to_datetime(pd.Series(values).dropna().unique())
    if len(uniq) == 0:
        return None
    return uniq[abs(uniq - target).argmin()]


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
    clicked_raw = pd.to_datetime(points[0]["x"])
    clicked = _nearest_period(detail_df[period_col], clicked_raw)
    if clicked is None:
        st.caption("No detail rows to show.")
        return
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
        # round(), not int(), for the same reason period_drilldown snaps to the
        # nearest period: a bar/marker click can report a slightly off-center x.
        year, moy = int(fig.data[curve_number].name), round(float(point["x"]))
    except (TypeError, ValueError):
        st.caption("Couldn't determine which year was clicked.")
        return
    moy = min(12, max(1, moy))
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


# ══════════════════════════════════════════════════════════════════════════════
# Redesign components (spec §04). Additive — existing helpers above are unchanged
# and views migrate to these in Phase B.
# ══════════════════════════════════════════════════════════════════════════════

CHART_HEIGHTS = {"compact": 240, "std": 320, "tall": 400}

_NS_SEQ = 0  # monotonic suffix for kpi_strip's north-star container key

_DRILL_HINT = "💡 Click a bar or point to break it down for that period. Click again to clear."

_STATE_CHIP = {
    "critical": ("🔴", "red"), "serious": ("🟠", "orange"), "warning": ("🟡", "yellow"),
    "good": ("🟢", "green"), "info": ("🔵", "blue"),
    "revision": ("↻", "violet"), "edited": ("✏️", "gray"),
    "matched": ("🔗", "green"), "unmatched": ("⚠️", "orange"),
}


def page_scaffold(title: str, purpose: str | None = None, actions=None) -> None:
    """Canonical page top: title, one-line purpose, optional right-aligned actions.
    Supersedes page_header() — same behaviour, plus the purpose line is styled via
    the .gpc-purpose class from dashboard/theme.py. Call scope_bar() next, then
    kpi_strip(), then the page's headline chart, then supporting section_card()s,
    then the detail table — that fixed order is the whole point (spec §04)."""
    if actions is not None:
        head = st.container(horizontal=True, horizontal_alignment="right")
        with head:
            st.title(title)
        with head:
            actions()
    else:
        st.title(title)
    if purpose:
        st.markdown(f'<p class="gpc-purpose">{purpose}</p>', unsafe_allow_html=True)


def scope_bar(fs, *, order_count: int | None = None) -> None:
    """One-line "Showing…" chip row rendered under the page title, echoing the top
    filter bar's state so the active scope travels with the content. `fs` is a
    filters.FilterState (read duck-typed, so any object with the same attributes
    works)."""
    chips: list[tuple[str, str]] = []
    if order_count is not None:
        chips.append(("is-accent", f"{order_count:,} orders"))

    start, end = getattr(fs, "start_ts", None), getattr(fs, "end_ts", None)
    if start is not None and end is not None:
        chips.append(("", f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"))
    else:
        chips.append(("", "All dates"))

    if getattr(fs, "has_comparison", False):
        chips.append(("is-accent", "vs same period last year"
                      if getattr(fs, "compare_mode", "") == "yoy" else "vs previous period"))

    cust = getattr(fs, "selected_customers", []) or []
    chips.append(("", f"{len(cust)} customer(s)" if cust else "All customers"))
    prod = getattr(fs, "selected_products", []) or []
    if prod:
        chips.append(("", f"{len(prod)} product(s)"))
    size = getattr(fs, "selected_sizes", []) or []
    if size:
        chips.append(("", f"{len(size)} size(s)"))
    lts = getattr(fs, "line_types", []) or []
    chips.append(("", " + ".join(lts) if lts else "no line types"))

    html = '<div class="gpc-scope">' + "".join(
        f'<span class="gpc-chip {cls}">{txt}</span>' for cls, txt in chips
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def kpi_strip(items: list[dict], north_star: int | None = 0) -> None:
    """Up to 6 equal-height metric tiles in bordered columns. Item keys:
    label, value, delta (opt), delta_help (opt caption), help (opt tooltip),
    chart_data (opt sparkline), chart_type (opt, default "line"). `north_star` is
    the index that gets the "★ " marker (and the accent underline, once
    dashboard/theme.py's rule is active); pass None for a plain strip with no
    highlighted metric."""
    if not items:
        return
    items = items[:6]
    # Keyed container so theme.py can accent the north-star strip's first tile.
    # A monotonic suffix keeps the key unique even if a page (or a test harness)
    # renders several starred strips; theme.py matches on the class prefix.
    if north_star is not None:
        global _NS_SEQ
        _NS_SEQ += 1
        box = st.container(key=f"gpc_kpi_ns_{_NS_SEQ}")
    else:
        box = st.container()
    with box:
        cols = st.columns(len(items), border=True)
        for i, (col, item) in enumerate(zip(cols, items)):
            kwargs = {}
            if item.get("chart_data") is not None and len(item["chart_data"]) >= 2:
                kwargs["chart_data"] = item["chart_data"]
                kwargs["chart_type"] = item.get("chart_type", "line")
            label = item["label"]
            if north_star is not None and i == north_star:
                label = f"★ {label}"
            col.metric(
                label, item["value"], delta=item.get("delta"),
                help=item.get("help"), **kwargs,
            )
            if item.get("delta_help"):
                col.caption(item["delta_help"])


def chart_frame(fig, *, palette: dict, key: str, title: str | None = None,
                size: str = "std", hint: str | None = None) -> None:
    """Plain (non-drilldown) chart with a standard frame: optional bold title above,
    one of three height tiers, style() applied, optional caption below. For
    click-to-drill charts keep using period_drilldown / yoy_drilldown — they already
    standardise the hint text (see _DRILL_HINT)."""
    if title:
        st.markdown(f"**{title}**")
    st.plotly_chart(
        style(fig, palette, height=CHART_HEIGHTS.get(size, 320)),
        use_container_width=True, key=key,
    )
    if hint:
        st.caption(hint)


def _column_config_for(cols) -> dict:
    cfg = {}
    for raw in cols:
        disp = col_label(raw)
        kind = COLUMN_KIND.get(raw)
        if kind == "currency":
            cfg[disp] = st.column_config.NumberColumn(disp, format="dollar")
        elif kind == "percent":
            cfg[disp] = st.column_config.NumberColumn(disp, format="%.1f%%")
        elif kind == "qty":
            cfg[disp] = st.column_config.NumberColumn(disp, format="localized")
        elif kind == "int":
            cfg[disp] = st.column_config.NumberColumn(disp, format="%d")
        elif kind == "date":
            cfg[disp] = st.column_config.DateColumn(disp)
    return cfg


def data_grid(df, columns: list[str] | None = None, *, key: str,
              download_name: str | None = None, height=None) -> None:
    """A dataframe rendered the standard way: columns picked (and ordered) via
    `columns`, relabelled through labels.COLUMN_LABELS, auto-formatted ($ / % / qty
    / date) via labels.COLUMN_KIND, then a bottom-right "Export this table (CSV)"
    button. Replaces every per-view rename map + ad-hoc download button."""
    show = df if columns is None else df[[c for c in columns if c in df.columns]]
    cfg = _column_config_for(show.columns)
    show = show.rename(columns={c: col_label(c) for c in show.columns})
    data_table(show, column_config=cfg, height=height)
    if download_name:
        st.download_button(
            "Export this table (CSV)",
            show.to_csv(index=False).encode("utf-8"),
            file_name=download_name, mime="text/csv", key=f"dl_{key}",
        )


def state_chip(kind: str, text: str | None = None) -> None:
    """One badge vocabulary for row/entity state: the five severities plus
    revision / edited / matched / unmatched."""
    icon, color = _STATE_CHIP.get(kind, ("⚪", "gray"))
    st.badge(text or kind.capitalize(), icon=icon, color=color)


def loading(message: str = "Loading…"):
    """`with loading():` — a labelled spinner. Thin, but keeps the call site
    consistent with empty()/error()."""
    return st.spinner(message)


def error(message: str, detail: str | None = None) -> None:
    """A query/compute failure shown in a bordered card — never a raw traceback.
    `message` says what failed; `detail` says what to check."""
    with st.container(border=True):
        st.error(message)
        if detail:
            st.caption(detail)


def metric_help(term: str) -> str | None:
    """Glossary tooltip text for a KPI label / term (spec decision #5)."""
    return GLOSSARY.get(term)
