"""Data Management → Raw Data. Redesign Phase B: page_scaffold + scope_bar + data_grid."""

import streamlit as st

from ui_kit import data_grid, page_scaffold, scope_bar


def render(ctx) -> None:
    f_items = ctx.f_items

    page_scaffold("Raw Data", "Filtered line items — current version of each PO, for the current scope.")
    scope_bar(ctx.fs, order_count=int(f_items["po_id"].nunique()) if not f_items.empty else 0)

    display_cols = [
        "po_number", "effective_date", "customer_name", "product_name", "container_size",
        "quantity", "unit_price", "line_total", "is_sample", "needs_review", "math_mismatch",
    ]
    data_grid(f_items, display_cols, key="raw", download_name="po_line_items.csv")
