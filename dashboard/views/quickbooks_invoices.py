"""
QuickBooks → Invoice Explorer. Phase 4: page_header/section_card/data_table polish.
Queries the synced tables directly regardless of current connection state, since a
prior sync's data should stay browsable even if the app later disconnects.
"""

import pandas as pd
import psycopg2
import streamlit as st

from data import get_database_url
from ui_kit import data_table, page_header, section_card


def render(ctx) -> None:
    page_header("Invoice Explorer")

    inv_conn = psycopg2.connect(get_database_url())
    try:
        invoices_df = pd.read_sql_query(
            "SELECT doc_number, customer_name, txn_date, ship_date, due_date, "
            "total_amt, private_note, raw_json FROM qbo_invoices "
            "ORDER BY txn_date DESC NULLS LAST",
            inv_conn,
        )
    finally:
        inv_conn.close()

    with section_card("Invoices"):
        if invoices_df.empty:
            st.caption("No invoices synced yet — visit Connection & Sync to connect and sync.")
        else:
            data_table(
                invoices_df.drop(columns=["raw_json"]).rename(columns={
                    "doc_number": "Doc #", "customer_name": "Customer", "txn_date": "Invoice Date",
                    "ship_date": "Ship Date", "due_date": "Due Date", "total_amt": "Total ($)",
                    "private_note": "Private Note",
                }),
            )
            with st.expander("Inspect one raw invoice (for designing Phase 2's matcher)"):
                idx = st.number_input("Row index", min_value=0, max_value=len(invoices_df) - 1, value=0)
                st.json(invoices_df.iloc[int(idx)]["raw_json"])

    cat_conn = psycopg2.connect(get_database_url())
    try:
        items_df = pd.read_sql_query(
            "SELECT name, item_type, active, category, product_name, container_size, "
            "unit_price, sku FROM qbo_items ORDER BY category, name",
            cat_conn,
        )
    finally:
        cat_conn.close()

    with section_card(
        "Item Catalog",
        "QuickBooks' own Item list — the product master catalog invoice lines are "
        "matched against by ID. Read-only here; re-synced each time you sync on the "
        "Connection & Sync page.",
    ):
        if items_df.empty:
            st.caption("No catalog synced yet — visit Connection & Sync to connect and sync.")
        else:
            counts = items_df["category"].value_counts()
            cat_cols = st.columns(len(counts))
            for col, (cat, n) in zip(cat_cols, counts.items()):
                col.metric(cat.capitalize(), n)
            data_table(
                items_df.rename(columns={
                    "name": "Name", "item_type": "QBO Type", "active": "Active",
                    "category": "Category", "product_name": "Product", "container_size": "Size",
                    "unit_price": "List Price ($)", "sku": "SKU",
                }),
            )
