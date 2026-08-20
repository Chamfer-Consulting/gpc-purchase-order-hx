"""
📦 Fulfillment → Match & Review. Phase 3 redesign: the "Needs review" queue splits into
Quick confirm (Certain/High confidence — dense one-row list) and Needs judgment
(everything else — full side-by-side detail opened via st.dialog instead of always-
rendered expanders), plus a score-breakdown popover using the new additive
qbo_matcher.explain_candidate(). Automated-matching buttons and the manual
search-and-match workbench are otherwise unchanged from Phase 1 — every `workbench_*`
session_state key stays exactly as it was.
"""

import pandas as pd
import psycopg2
import streamlit as st

import gdrive_client
import qbo_client
import qbo_matcher
from data import get_database_url
from ui_kit import confidence_badge, data_table, page_header, section_card


def _items_table(items):
    if not items:
        st.caption("No line items.")
        return
    data_table(
        pd.DataFrame(items).rename(columns={
            "product_name": "Product", "container_size": "Size", "quantity": "Qty",
            "unit_price": "Unit $", "line_total": "Total $", "is_sample": "Sample",
            "category": "Category",
        }),
    )


def _score_breakdown(mc, row) -> None:
    explain = qbo_matcher.explain_candidate(mc, row["po_id"], row["invoice_id"])
    if not explain:
        return
    with st.popover("Why this score?"):
        st.caption(f"Weighted total: **{explain['weighted_total']}**")
        date_note = (
            f"({explain['date_delta_days']}d gap, window ±{explain['date_window_days']}d"
            + (", outside window" if explain["outside_date_window"] else "") + ")"
            if explain["date_delta_days"] is not None else "(no date to compare)"
        )
        st.write(f"📅 Date match: {explain['date_score']} {date_note}")
        st.write(f"💲 Amount match: {explain['amount_score']}")
        st.write(f"📦 Line-item overlap: {explain['item_score']}")
        st.write(f"🔢 PO-number hint: {explain['hint_score']}")


@st.dialog("Review match", width="large")
def _review_dialog(mc, row: dict, po_items_map: dict, inv_items_map: dict) -> None:
    confidence = qbo_matcher.confidence_label(row["match_method"], row["match_score"])
    hc1, hc2 = st.columns([3, 2])
    with hc1:
        confidence_badge(confidence)
    with hc2:
        _score_breakdown(mc, row)

    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("**Purchase Order**")
        st.write(f"PO Number: {row['po_number'] or row['source_file']}")
        if row.get("drive_file_id"):
            st.markdown(f"[📄 Open original PDF ↗]({gdrive_client.file_view_url(row['drive_file_id'])})")
        st.write(f"Customer: {row['po_customer']}")
        st.write(
            f"PO Date: {row['po_date'] or '—'} · Sent: {row['sent_date'] or '—'} · "
            f"Delivery: {row['delivery_date'] or '—'}"
        )
        st.write(
            f"Subtotal: ${row['po_subtotal'] or 0:,.2f} · Tax: ${row['po_tax'] or 0:,.2f} · "
            f"Total: ${row['po_total'] or 0:,.2f}"
        )
        if row.get("po_notes"):
            st.caption(f"Notes: {row['po_notes']}")
        _items_table(po_items_map.get(row["po_id"], []))
    with dc2:
        st.markdown("**QuickBooks Invoice**")
        st.write(f"Invoice #: {row['doc_number']}")
        st.markdown(f"[Open in QuickBooks ↗]({qbo_client.invoice_url(row['qbo_invoice_id'])})")
        st.write(f"Customer: {row['inv_customer']}")
        st.write(f"Invoice Date: {row['txn_date'] or '—'} · Due: {row['due_date'] or '—'}")
        st.write(f"Total: ${row['total_amt'] or 0:,.2f}")
        if row.get("inv_note"):
            st.caption(f"Note: {row['inv_note']}")
        _items_table(inv_items_map.get(row["invoice_id"], []))

    bc1, bc2 = st.columns(2)
    if bc1.button("✅ Confirm match", key=f"dlg_confirm_{row['po_id']}_{row['invoice_id']}", type="primary"):
        qbo_matcher.confirm_link(mc, row["po_id"], row["invoice_id"])
        st.rerun()
    if bc2.button("❌ Reject", key=f"dlg_reject_{row['po_id']}_{row['invoice_id']}"):
        qbo_matcher.reject_link(mc, row["po_id"], row["invoice_id"])
        st.rerun()


def _review_row(row: dict, confidence: str, mc, po_items_map: dict, inv_items_map: dict) -> None:
    rc1, rc2, rc3 = st.columns([5, 2, 2])
    rc1.write(
        f"**PO {row['po_number'] or row['source_file']}** ({row['po_customer']}, "
        f"${row['po_total'] or 0:,.2f}) ↔ **Invoice {row['doc_number']}** "
        f"({row['inv_customer']}, {row['txn_date']}, ${row['total_amt'] or 0:,.2f})"
    )
    with rc2:
        confidence_badge(confidence)
    if rc3.button("Review", key=f"review_{row['po_id']}_{row['invoice_id']}"):
        _review_dialog(mc, row, po_items_map, inv_items_map)


def render(ctx) -> None:
    page_header(
        "Match & Review",
        "Match PO requests to QuickBooks invoices — run automated matching, review its "
        "suggestions, or search and link manually. See **Requested vs Delivered** "
        "alongside this page for the resulting report.",
    )

    mc = psycopg2.connect(get_database_url())

    try:
        with section_card("Automated matching"):
            mcol1, mcol2 = st.columns(2)
            if mcol1.button("🔄 Run matching"):
                with st.spinner("Matching POs to invoices..."):
                    summary = qbo_matcher.run_matching(mc)
                st.success(
                    f"{summary['auto_matched']} auto-matched with certainty, "
                    f"{summary['customer_mismatch']} PO-number match(es) held for review "
                    f"(customer didn't corroborate), "
                    f"{summary['fuzzy_candidates']} fuzzy candidate(s) added for review, "
                    f"{summary['ambiguous_po_number']} still-ambiguous PO-number match(es), "
                    f"{summary['no_candidates']} PO(s) with no candidate at all "
                    f"(out of {summary['total_pos']} total POs). "
                    f"{summary['voided_released']} PO(s) released back for rematching (their "
                    f"invoice was voided in QuickBooks), {summary['voided_pruned']} stale voided "
                    f"candidate(s) pruned. "
                    f"Fuzzy date window: ±{summary['date_window_days']} days."
                )
            if mcol2.button("📁 Sync Drive links"):
                progress_bar = st.progress(0.0, text="Searching Google Drive...")

                def _drive_progress(i, total):
                    progress_bar.progress(i / total, text=f"Searching Google Drive... {i}/{total}")

                try:
                    drive_summary = gdrive_client.sync_drive_links(mc, progress=_drive_progress)
                    progress_bar.empty()
                    msg = (
                        f"{drive_summary['linked']} PO(s) linked to their PDF, "
                        f"{drive_summary['not_found']} not found in this batch "
                        f"(checked {drive_summary['total_checked']})."
                    )
                    if drive_summary["remaining"]:
                        msg += f" {drive_summary['remaining']} more PO(s) still to check — click again to continue."
                    st.success(msg)
                except Exception as e:
                    progress_bar.empty()
                    st.error(f"Drive sync failed: {e}")
            with mc.cursor() as _cur:
                _cur.execute("SELECT COUNT(*), COUNT(drive_file_id) FROM purchase_orders WHERE error IS NULL")
                _total_po, _linked_po = _cur.fetchone()
            st.caption(f"📁 {_linked_po} of {_total_po} POs linked to their original PDF in Google Drive.")

        st.subheader("Needs review")
        needs_review = qbo_matcher.get_needs_review(mc)
        if not needs_review:
            st.caption("Nothing pending review.")
        else:
            po_items_map, inv_items_map = qbo_matcher.get_line_items_for_review(
                mc, [r["po_id"] for r in needs_review], [r["invoice_id"] for r in needs_review],
            )
            annotated = [
                (r, qbo_matcher.confidence_label(r["match_method"], r["match_score"]))
                for r in needs_review
            ]
            quick = [(r, c) for r, c in annotated if qbo_matcher.is_quick_confirm(c)]
            judgment = [(r, c) for r, c in annotated if not qbo_matcher.is_quick_confirm(c)]

            if quick:
                with section_card(f"✅ Quick confirm ({len(quick)})", "High-confidence matches — spot-check and confirm."):
                    for row, confidence in quick:
                        _review_row(row, confidence, mc, po_items_map, inv_items_map)

            if judgment:
                with section_card(
                    f"🤔 Needs judgment ({len(judgment)})",
                    "Lower-confidence or ambiguous matches — open each to compare in full detail.",
                ):
                    for row, confidence in judgment:
                        _review_row(row, confidence, mc, po_items_map, inv_items_map)

        st.divider()
        st.subheader("🔍 Search & match manually")
        unresolved_count = len(qbo_matcher.get_unlinked_pos(mc))
        st.caption(
            "Find and link any PO to any invoice directly — independent of the automated "
            f"suggestions above. {unresolved_count} PO(s) still without a confirmed match."
        )

        wc1, wc2 = st.columns(2)
        selected_po = selected_invoice = None
        po_detail = None

        with wc1:
            st.markdown("**Purchase Order**")
            po_search = st.text_input("Search PO number, customer, or filename", key="workbench_po_search")
            po_include_matched = st.checkbox("Include already-matched POs", key="workbench_po_include_matched")
            po_results = qbo_matcher.search_pos(mc, po_search, limit=50, include_matched=po_include_matched)
            if not po_results:
                st.caption("No matching POs.")
            else:
                po_label_map = {
                    f"{p['po_number'] or p['source_file']} — {p['customer_name']} — ${p['total'] or 0:,.2f}": p["id"]
                    for p in po_results
                }
                picked_po_label = st.selectbox("Results", list(po_label_map.keys()), key="workbench_po_pick")
                selected_po = po_label_map[picked_po_label]

            if selected_po:
                po_detail = qbo_matcher.get_po_full_detail(mc, selected_po)
                st.write(f"PO Number: {po_detail['po_number'] or po_detail['source_file']}")
                if po_detail.get("drive_file_id"):
                    st.markdown(f"[📄 Open original PDF ↗]({gdrive_client.file_view_url(po_detail['drive_file_id'])})")
                st.write(f"Customer: {po_detail['customer_name']}")
                st.write(
                    f"PO Date: {po_detail['po_date'] or '—'} · Sent: {po_detail['sent_date'] or '—'} · "
                    f"Delivery: {po_detail['delivery_date'] or '—'}"
                )
                st.write(
                    f"Subtotal: ${po_detail['subtotal'] or 0:,.2f} · Tax: ${po_detail['tax'] or 0:,.2f} · "
                    f"Total: ${po_detail['total'] or 0:,.2f}"
                )
                _items_table(po_detail["items"])

        with wc2:
            st.markdown("**QuickBooks Invoice**")
            default_customer = po_detail["customer_name"] if po_detail else ""
            inv_customer = st.text_input("Customer", value=default_customer or "", key="workbench_inv_customer")
            inv_query = st.text_input("Search invoice #", key="workbench_inv_query")
            ic1, ic2 = st.columns(2)
            amount_min = ic1.number_input("Min $", value=0.0, step=10.0, key="workbench_inv_min")
            amount_max = ic2.number_input("Max $ (0 = no limit)", value=0.0, step=10.0, key="workbench_inv_max")
            ic3, ic4 = st.columns(2)
            include_voided = ic3.checkbox("Include voided/zero-$ invoices", key="workbench_inv_voided")
            inv_include_matched = ic4.checkbox("Include already-matched invoices", key="workbench_inv_include_matched")
            inv_results = qbo_matcher.search_invoices(
                mc, customer=inv_customer, query=inv_query,
                amount_min=(amount_min or None), amount_max=(amount_max or None),
                include_voided=include_voided, include_matched=inv_include_matched, limit=100,
            )
            if not inv_results:
                st.caption("No matching invoices.")
            else:
                inv_label_map = {
                    f"{i['doc_number']} — {i['customer_name']} — {i['txn_date']} — ${i['total_amt'] or 0:,.2f}": i["id"]
                    for i in inv_results
                }
                picked_inv_label = st.selectbox("Results", list(inv_label_map.keys()), key="workbench_inv_pick")
                selected_invoice = inv_label_map[picked_inv_label]

            if selected_invoice:
                inv_detail = qbo_matcher.get_invoice_full_detail(mc, selected_invoice)
                st.write(f"Invoice #: {inv_detail['doc_number']}")
                st.markdown(f"[Open in QuickBooks ↗]({qbo_client.invoice_url(inv_detail['qbo_invoice_id'])})")
                st.write(f"Customer: {inv_detail['customer_name']}")
                st.write(f"Invoice Date: {inv_detail['txn_date'] or '—'} · Due: {inv_detail['due_date'] or '—'}")
                st.write(f"Total: ${inv_detail['total_amt'] or 0:,.2f}")
                if inv_detail.get("private_note"):
                    st.caption(f"Note: {inv_detail['private_note']}")
                _items_table(inv_detail["items"])

        if selected_po and selected_invoice:
            st.markdown("---")
            replace_existing = False
            existing_po_links = qbo_matcher.get_confirmed_invoices_for_po(mc, selected_po)
            if existing_po_links:
                names = ", ".join(f"{l['doc_number']} (${l['total_amt'] or 0:,.2f})" for l in existing_po_links)
                st.warning(f"This PO is already confirmed-linked to: {names}")
                replace_existing = st.checkbox("Replace existing link(s) with this one", key="workbench_replace")

            other_po = qbo_matcher.get_confirmed_po_for_invoice(mc, selected_invoice)
            if other_po and other_po["id"] != selected_po:
                st.warning(
                    f"This invoice is already confirmed to a different PO: "
                    f"{other_po['po_number'] or other_po['source_file']}. Linking it here too is "
                    f"allowed (e.g. split shipments) but double-check this is intentional."
                )

            if st.button("🔗 Link these"):
                qbo_matcher.manual_link(mc, selected_po, selected_invoice, replace_existing=replace_existing)
                st.success("Linked.")
                st.rerun()
    finally:
        mc.close()
