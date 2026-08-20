"""🗂️ Data Management → Raw Data. Phase 4: page_header/data_table polish."""

import streamlit as st

from ui_kit import data_table, page_header


def render(ctx) -> None:
    f_items = ctx.f_items

    page_header("Raw Data", "Filtered line items — current version of each PO, per the sidebar filters.")

    display_cols = [
        "po_number", "effective_date", "customer_name", "product_name", "container_size",
        "quantity", "unit_price", "line_total", "is_sample", "needs_review", "math_mismatch",
    ]
    table = f_items[display_cols].rename(columns={
        "po_number": "PO Number", "effective_date": "Date", "customer_name": "Customer",
        "product_name": "Product", "container_size": "Size", "quantity": "Qty",
        "unit_price": "Unit Price ($)", "line_total": "Line Total ($)",
        "is_sample": "Sample", "needs_review": "Review", "math_mismatch": "Math Check",
    })
    data_table(table)
    st.download_button(
        "⬇️ Download as CSV",
        table.to_csv(index=False).encode("utf-8"),
        file_name="po_line_items.csv",
        mime="text/csv",
        key="dl_raw",
    )
