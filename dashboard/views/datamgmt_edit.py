"""
Data Management → Edit PO. Phase 4: page_header/section_card polish only — every
per-PO session_state key (f"..._{selected_id}") is preserved exactly, byte-for-byte,
per the plan's risk notes; the {selected_id} suffix is what intentionally resets the
form when a different PO is picked. The form/data_editor structure itself is untouched.
"""

import pandas as pd
import streamlit as st

from data import load_data, save_po_edit
from ui_kit import page_header, section_card


def render(ctx) -> None:
    latest_po, all_items = ctx.latest_po, ctx.all_items

    page_header(
        "Edit PO",
        "Edits are permanent — once saved, that PO stops receiving updates from future "
        "extraction syncs (its header and line items are frozen as you leave them here).",
    )

    picker = latest_po.sort_values("po_number", na_position="last")
    label_to_id = {
        f"{row.po_number or row.source_file} — {row.customer_name or 'Unknown customer'}": int(row.id)
        for row in picker.itertuples()
    }
    selected_label = st.selectbox("Select a PO to edit", options=list(label_to_id.keys()))
    selected_id = label_to_id.get(selected_label)

    if selected_id is not None:
        row = latest_po[latest_po["id"] == selected_id].iloc[0]
        if bool(row.get("edited")):
            st.info(f"This record was already manually edited (at {row.get('edited_at')}).")

        with section_card():
            with st.form(f"edit_form_{selected_id}"):
                c1, c2 = st.columns(2)
                po_number = c1.text_input("PO Number", value=row["po_number"] or "", key=f"po_number_{selected_id}")
                customer_name = c2.text_input("Customer", value=row["customer_name"] or "", key=f"customer_{selected_id}")
                po_date = c1.date_input(
                    "PO Date", value=row["po_date"].date() if pd.notna(row["po_date"]) else None, key=f"po_date_{selected_id}",
                )
                delivery_date = c2.date_input(
                    "Delivery Date", value=row["delivery_date"].date() if pd.notna(row["delivery_date"]) else None,
                    key=f"delivery_date_{selected_id}",
                )
                subtotal = c1.number_input(
                    "Subtotal ($)", value=float(row["subtotal"]) if pd.notna(row["subtotal"]) else 0.0,
                    step=0.01, format="%.2f", key=f"subtotal_{selected_id}",
                )
                tax = c2.number_input(
                    "Tax ($)", value=float(row["tax"]) if pd.notna(row["tax"]) else 0.0,
                    step=0.01, format="%.2f", key=f"tax_{selected_id}",
                )
                total = c1.number_input(
                    "Total ($)", value=float(row["total"]) if pd.notna(row["total"]) else 0.0,
                    step=0.01, format="%.2f", key=f"total_{selected_id}",
                )
                notes = st.text_area("Notes", value=row["notes"] or "", key=f"notes_{selected_id}")

                st.markdown("**Line items**")
                items_seed = all_items[all_items["po_id"] == selected_id][
                    ["product_name", "container_size", "quantity", "unit_price", "line_total", "is_sample"]
                ].reset_index(drop=True)
                edited_items = st.data_editor(
                    items_seed, num_rows="dynamic", use_container_width=True, key=f"items_editor_{selected_id}",
                    column_config={
                        "quantity": st.column_config.NumberColumn("Qty"),
                        "unit_price": st.column_config.NumberColumn("Unit Price ($)", format="%.2f"),
                        "line_total": st.column_config.NumberColumn("Line Total ($)", format="%.2f"),
                        "is_sample": st.column_config.CheckboxColumn("Sample"),
                    },
                )

                submitted = st.form_submit_button("Save changes")

        if submitted:
            items = [
                item for item in edited_items.to_dict("records")
                if item.get("product_name")  # drop blank rows added via the "+" control
            ]
            header = {
                "po_number": po_number or None,
                "customer_name": customer_name or None,
                "po_date": po_date,
                "delivery_date": delivery_date,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "notes": notes or None,
            }
            save_po_edit(selected_id, header, items)
            load_data.clear()
            st.success("Saved.")
            st.rerun()
