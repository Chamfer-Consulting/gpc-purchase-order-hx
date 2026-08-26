"""
One scoped `<style>` block, injected once from app.py after the theme type is
known. Deliberately small: it styles the redesign's own wrapper classes
(`.gpc-scope`, `.gpc-chip`, `.gpc-filterbar`, the KPI north-star hook) and applies
a light type/spacing polish to a few stable Streamlit testids. It does NOT try to
re-skin every widget — Streamlit's native Light/Dark theming still does that.

Colours come from dashboard/data.py's validated LIGHT/DARK palette so there's one
source of truth; this module only turns the active palette into CSS custom
properties and a handful of rules.
"""

from __future__ import annotations

import streamlit as st

from data import DARK, LIGHT


def _tokens(palette: dict) -> str:
    return "\n".join(
        f"  --gpc-{k.replace('_', '-')}: {v};"
        for k, v in palette.items()
        if isinstance(v, str)
    ) + "\n".join(
        f"\n  --gpc-status-{k}: {v};" for k, v in palette.get("status", {}).items()
    )


_RULES = """
/* redesign wrapper classes -------------------------------------------------- */
.gpc-scope{
  display:flex;flex-wrap:wrap;gap:6px;align-items:center;
  margin:.15rem 0 1rem;font-size:.78rem;
}
.gpc-chip{
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  padding:2px 9px;border-radius:999px;line-height:1.6;
  border:1px solid var(--gpc-grid);
  color:var(--gpc-ink-muted);background:var(--gpc-surface);
  font-variant-numeric:tabular-nums;
}
.gpc-chip::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--gpc-ink-muted);flex:none}
.gpc-chip.is-accent{color:var(--gpc-status-good);border-color:var(--gpc-status-good)}
.gpc-chip.is-accent::before{background:var(--gpc-status-good)}
.gpc-chip.is-warn{color:var(--gpc-status-warning);border-color:var(--gpc-status-warning)}
.gpc-chip.is-warn::before{background:var(--gpc-status-warning)}
.gpc-chip.is-crit{color:var(--gpc-status-critical);border-color:var(--gpc-status-critical)}
.gpc-chip.is-crit::before{background:var(--gpc-status-critical)}
.gpc-purpose{color:var(--gpc-ink-muted);font-size:.92rem;margin:-.35rem 0 .5rem}

/* north-star KPI tile: ui_kit.kpi_strip prefixes its label with "★ ". The
   accent-underline treatment is a Phase F polish item (needs a per-strip hook
   that doesn't collide when a page renders more than one strip). */

/* quiet polish on stable testids ----------------------------------------------
   kept minimal + defensive: only spacing / weight, no layout takeovers */
[data-testid="stMetricLabel"] p{
  font-size:.72rem !important;letter-spacing:.06em;text-transform:uppercase;
  color:var(--gpc-ink-muted);
}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums}
h1,h2,h3{letter-spacing:-.01em}
"""


def inject(theme_type: str | None) -> None:
    """Inject the scoped stylesheet. Call once, early, after the theme type is
    known (app.py already resolves `theme_type`)."""
    palette = DARK if theme_type == "dark" else LIGHT
    st.markdown(
        f"<style>\n:root {{\n{_tokens(palette)}\n}}\n{_RULES}\n</style>",
        unsafe_allow_html=True,
    )
