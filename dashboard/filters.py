"""
The comprehensive sticky filter bar that replaces the old sidebar filter block
(redesign spec §03, decision #2).

`render_filter_bar()` draws the bar and returns a `FilterState`; app.py turns that
into the filtered dataframes on `AppContext`, exactly where the sidebar code used
to. Widget keys are all `flt_*` so nothing collides with the pages' own state, and
"Reset" clears just those.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from labels import LINE_TYPE_GROUPS

_PRESETS = [
    "Last 30 days", "Last 90 days", "Year to date",
    "This year", "Last year", "All time", "Custom",
]
_COMPARE = ["No comparison", "vs previous period", "vs same period last year"]
_COMPARE_KEY = {"No comparison": "none", "vs previous period": "prev",
                "vs same period last year": "yoy"}
_DEFAULT_LINE_TYPES = ["Sales", "Donations", "Shipping"]
_FLT_KEYS = (
    "flt_preset", "flt_year", "flt_custom", "flt_compare",
    "flt_customers", "flt_products", "flt_sizes", "flt_line_types",
)


@dataclass
class FilterState:
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None
    preset: str
    compare_mode: str                       # "none" | "prev" | "yoy"
    prev_start: pd.Timestamp | None
    prev_end: pd.Timestamp | None
    selected_customers: list[str] = field(default_factory=list)
    selected_products: list[str] = field(default_factory=list)
    selected_sizes: list[str] = field(default_factory=list)
    line_types: list[str] = field(default_factory=list)     # keys of LINE_TYPE_GROUPS

    @property
    def include_samples(self) -> bool:
        return "Samples" in self.line_types

    @property
    def categories(self) -> list[str]:
        """Flattened qbo invoice-line categories in scope, from the picked groups."""
        out: list[str] = []
        for group in self.line_types:
            out.extend(LINE_TYPE_GROUPS.get(group, ()))
        return out

    @property
    def has_comparison(self) -> bool:
        return self.compare_mode != "none" and self.prev_start is not None


def reset() -> None:
    for k in _FLT_KEYS:
        st.session_state.pop(k, None)


def _resolve_range(preset: str, min_d, max_d):
    """(start_ts, end_ts) for a preset. `Year`-style pickers read st.session_state
    directly since their sub-widget is drawn by the caller."""
    if pd.isna(min_d) or pd.isna(max_d):
        return None, None
    today = pd.Timestamp(max_d.date())
    if preset == "Last 30 days":
        return today - pd.Timedelta(days=29), today
    if preset == "Last 90 days":
        return today - pd.Timedelta(days=89), today
    if preset == "Year to date":
        return pd.Timestamp(year=today.year, month=1, day=1), today
    if preset == "This year":
        return pd.Timestamp(year=today.year, month=1, day=1), pd.Timestamp(year=today.year, month=12, day=31)
    if preset == "Last year":
        y = today.year - 1
        return pd.Timestamp(year=y, month=1, day=1), pd.Timestamp(year=y, month=12, day=31)
    if preset == "Custom":
        cr = st.session_state.get("flt_custom")
        if isinstance(cr, (list, tuple)) and len(cr) == 2 and all(cr):
            return pd.Timestamp(cr[0]), pd.Timestamp(cr[1])
    return pd.Timestamp(min_d), pd.Timestamp(max_d)   # "All time" / incomplete custom


def _compare_range(mode: str, start, end):
    if mode == "none" or start is None or end is None:
        return None, None
    if mode == "yoy":
        return start - pd.DateOffset(years=1), end - pd.DateOffset(years=1)
    span = end - start                                   # "prev"
    prev_end = start - pd.Timedelta(days=1)
    return prev_end - span, prev_end


def _summary(pop, label: str, n: int) -> str:
    return f"{label} · {n}" if n else label


def render_filter_bar(min_date, max_date, customers, products, sizes) -> FilterState:
    """Draw the bar; return the resolved FilterState."""
    st.session_state.setdefault("flt_preset", "All time")
    st.session_state.setdefault("flt_compare", _COMPARE[0])
    st.session_state.setdefault("flt_line_types", list(_DEFAULT_LINE_TYPES))

    bar = st.container(border=True)
    with bar:
        c = st.columns([2.2, 2, 2, 2, 1.6, 2, 1.1], vertical_alignment="center")

        # ── date ──────────────────────────────────────────────────────────────
        with c[0].popover(f"📅 {st.session_state['flt_preset']}", use_container_width=True):
            preset = st.segmented_control(
                "Date range", _PRESETS, key="flt_preset",
                selection_mode="single", default="All time",
            ) or "All time"
            if preset == "Custom" and not (pd.isna(min_date) or pd.isna(max_date)):
                st.date_input(
                    "Custom range",
                    value=st.session_state.get("flt_custom", (min_date.date(), max_date.date())),
                    min_value=min_date.date(), max_value=max_date.date(), key="flt_custom",
                )
        preset = st.session_state["flt_preset"] or "All time"
        start_ts, end_ts = _resolve_range(preset, min_date, max_date)

        # ── compare ───────────────────────────────────────────────────────────
        with c[1].popover(f"⇄ {st.session_state['flt_compare']}", use_container_width=True):
            st.radio("Compare to", _COMPARE, key="flt_compare")
        compare_mode = _COMPARE_KEY[st.session_state["flt_compare"]]
        prev_start, prev_end = _compare_range(compare_mode, start_ts, end_ts)

        # ── customers ─────────────────────────────────────────────────────────
        sel_cust = st.session_state.get("flt_customers", [])
        with c[2].popover(_summary(None, "👥 Customers", len(sel_cust)), use_container_width=True):
            sel_cust = st.multiselect("Customers", customers, key="flt_customers")

        # ── products ──────────────────────────────────────────────────────────
        sel_prod = st.session_state.get("flt_products", [])
        with c[3].popover(_summary(None, "🥬 Products", len(sel_prod)), use_container_width=True):
            sel_prod = st.multiselect("Products", products, key="flt_products")

        # ── sizes ─────────────────────────────────────────────────────────────
        sel_size = st.session_state.get("flt_sizes", [])
        with c[4].popover(_summary(None, "📦 Sizes", len(sel_size)), use_container_width=True):
            sel_size = st.multiselect("Container sizes", sizes, key="flt_sizes")

        # ── line type ─────────────────────────────────────────────────────────
        lt = st.session_state.get("flt_line_types", list(_DEFAULT_LINE_TYPES))
        with c[5].popover(f"🧾 Line types · {len(lt)}", use_container_width=True):
            lt = st.multiselect(
                "Include in totals", list(LINE_TYPE_GROUPS.keys()), key="flt_line_types",
                help="Sales are product revenue. Donations, shipping and samples are "
                     "booked separately — toggle them in or out of every total.",
            )

        # ── reset ─────────────────────────────────────────────────────────────
        if c[6].button("↺ Reset", use_container_width=True):
            reset()
            st.rerun()

    return FilterState(
        start_ts=start_ts, end_ts=end_ts, preset=preset,
        compare_mode=compare_mode, prev_start=prev_start, prev_end=prev_end,
        selected_customers=sel_cust, selected_products=sel_prod,
        selected_sizes=sel_size, line_types=lt,
    )
