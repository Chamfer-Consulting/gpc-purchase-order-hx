"""
Settings & Connections — back-of-house (redesign spec §03). One page that groups
the pages that configure the system rather than analyse it: reference prices,
correcting an order, the raw line-item export, product visibility, and the
QuickBooks / Gmail connections.

A segmented control picks the section and only that section renders — unlike
st.tabs, which would execute every sub-page's queries (and the connection pages'
API calls) on every visit.
"""

import streamlit as st

from ui_kit import page_scaffold
from views import (
    datamgmt_edit,
    datamgmt_raw,
    email_ingestion,
    quickbooks_connection,
    reports_pricing,
    reports_products,
)

_SECTIONS = {
    "Reference prices": reports_pricing.render,
    "Correct an order": datamgmt_edit.render,
    "Raw line items": datamgmt_raw.render,
    "Products": reports_products.render,   # hosts the product-visibility toggle
    "QuickBooks": quickbooks_connection.render,
    "Email ingestion": email_ingestion.render,
}


def render(ctx) -> None:
    page_scaffold("Settings & Connections", "Configure pricing, fix data, and manage the QuickBooks and Gmail connections.")
    choice = st.segmented_control(
        "Section", list(_SECTIONS), default="Reference prices", key="settings_section",
        selection_mode="single",
    ) or "Reference prices"
    st.divider()
    _SECTIONS[choice](ctx)
