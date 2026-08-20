"""
Shared visual/component vocabulary for dashboard/views/*.py pages — built once here so
every page stops being visually ad hoc (see Phase 1 of
/Users/jcaternolo/.claude/plans/golden-soaring-robin.md). Composes on top of
dashboard/data.py's palette/style()/color_map_for() etc.; does not replace them.

Not yet imported by any page as of Phase 1 (foundation phase — the mechanical page
extraction is behavior-identical to the old app.py). Phases 2-4 apply these helpers
page by page.
"""

import streamlit as st

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
