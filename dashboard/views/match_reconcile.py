"""
Match & Reconcile — confirm PO <-> invoice links and browse the synced QuickBooks
data (redesign spec §03). Wraps the former Match & Review and Invoice Explorer
pages; a segmented control renders one at a time so the match workbench's queries
don't run when you just want to look at invoices.
"""

import streamlit as st

from ui_kit import page_scaffold
from views import fulfillment_match, quickbooks_invoices

_SECTIONS = {
    "Match & review": fulfillment_match.render,
    "Invoice explorer": quickbooks_invoices.render,
}


def render(ctx) -> None:
    page_scaffold("Match & Reconcile", "Confirm which QuickBooks invoice each purchase order was filled by, and browse the synced invoice and item data.")
    choice = st.segmented_control(
        "Section", list(_SECTIONS), default="Match & review", key="match_reconcile_section",
        selection_mode="single",
    ) or "Match & review"
    st.divider()
    _SECTIONS[choice](ctx)
