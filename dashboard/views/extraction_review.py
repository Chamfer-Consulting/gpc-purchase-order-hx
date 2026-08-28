"""
Extraction Review — the human-in-the-loop training queue for the PO importer.

Every decision here writes an extraction_reviews row, which the cloud pipeline
then treats as authoritative (skip / lock / force-or-forbid a revision), feeds
back into the extraction + gate prompts as a few-shot example, and eval_extraction.py
gates future prompt/model changes against. See extraction_reviews.py.
"""

import pandas as pd
import streamlit as st

from data import (
    load_extraction_reviews,
    load_review_queue,
    load_revision_candidates,
    save_extraction_review,
    delete_extraction_review,
)
from ui_kit import data_grid, page_scaffold, section_card

_REVIEWER = "dashboard"


def _po_context(ctx, po_id):
    """(header dict, items DataFrame) for one PO id, from the already-loaded ctx."""
    hdr = ctx.po_df[ctx.po_df["id"] == po_id]
    header = hdr.iloc[0].to_dict() if not hdr.empty else {}
    items = ctx.all_items[ctx.all_items["po_id"] == po_id]
    items = items[~items["is_removed"].fillna(False)] if "is_removed" in items.columns else items
    return header, items


def _line_editor_df(items: pd.DataFrame) -> pd.DataFrame:
    cols = ["product_raw", "container_size", "quantity", "unit_price", "line_total"]
    if items.empty:
        return pd.DataFrame(columns=cols)
    return items.reindex(columns=cols).reset_index(drop=True)


def _corrected_from(header: dict, edited: pd.DataFrame) -> dict:
    items = [
        {
            "product_raw": (r.get("product_raw") or "").strip(),
            "container_size": (r.get("container_size") or "").strip() or None,
            "quantity": r.get("quantity"),
            "unit_price": r.get("unit_price"),
            "line_total": r.get("line_total"),
        }
        for r in edited.to_dict("records")
        if (r.get("product_raw") or "").strip()
    ]
    return {
        "customer_name": header.get("customer_name") or None,
        "po_date": str(header["po_date"])[:10] if header.get("po_date") else None,
        "po_number": header.get("po_number") or None,
        "line_items": items,
    }


def _decision_form(ctx, row) -> None:
    """One queue entry: source text + current extraction + the verdict form."""
    tk, key = row["target_kind"], row["target_key"]
    po_id = int(row["po_id"])
    header, items = _po_context(ctx, po_id)

    title = row.get("subject") or key
    flags = f" · ⚠️ {row['reason']}" if row["reason"] else ""
    stale = " · 🕒 STALE" if row["stale"] else ""
    with st.expander(f"{title}{flags}{stale}", expanded=False):
        left, right = st.columns([3, 2])
        with left:
            st.caption(f"{row.get('from_addrs') or '—'}  ·  {tk}:{key}")
            if row.get("gmail_url"):
                st.markdown(f"[Open the email in Gmail ↗]({row['gmail_url']})")
            st.text_area(
                "What the extractor saw", value=row.get("snapshot") or "(no snapshot on file yet)",
                height=240, disabled=True, key=f"snap_{tk}_{key}",
            )
        with right:
            st.caption("Current extraction")
            st.write({
                "error": header.get("error") or None,
                "customer": header.get("customer_name"),
                "po_date": str(header.get("po_date"))[:10] if header.get("po_date") else None,
                "po_number": header.get("po_number"),
                "line items": int(len(items)),
            })

        verdict = st.radio(
            "Verdict", ["Purchase order", "Not a purchase order", "Revision of another PO"],
            horizontal=True, key=f"verdict_{tk}_{key}",
        )

        revision_of = None
        standalone = False
        corrected = None
        if verdict == "Purchase order":
            lock = st.checkbox(
                "Lock the line items below as correct (pins this PO; the importer stops re-guessing it)",
                key=f"lock_{tk}_{key}",
            )
            edited = st.data_editor(
                _line_editor_df(items), num_rows="dynamic", key=f"edit_{tk}_{key}",
                use_container_width=True,
            )
            if lock:
                corrected = _corrected_from(header, edited)
            standalone = st.checkbox(
                "This is its own PO — never fold it into a revision group",
                key=f"solo_{tk}_{key}",
            )
        elif verdict == "Revision of another PO":
            revision_of = st.text_input(
                "PO number (or gmail-thread:<id> / source_file) this revises",
                key=f"revof_{tk}_{key}",
            ).strip() or None
            st.caption(
                "On the next importer run this thread is re-extracted as the COMPLETE revised "
                "order — the model is given that PO's current line items plus this thread's "
                "change messages — and grouped under it. No need to enter line items here."
            )

        note = st.text_input("Note (optional — becomes part of the few-shot hint)", key=f"note_{tk}_{key}")

        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("Save decision", type="primary", key=f"save_{tk}_{key}"):
                v = {"Purchase order": "is_po", "Not a purchase order": "not_po",
                     "Revision of another PO": "is_po"}[verdict]
                save_extraction_review(
                    target_kind=tk, target_key=key, verdict=v,
                    revision_of=revision_of, standalone=standalone,
                    corrected=corrected, note=note or None, reviewer=_REVIEWER,
                )
                st.success("Saved. It applies on the next importer run and to the few-shot set.")
                st.rerun()


def render(ctx) -> None:
    page_scaffold(
        "Extraction Review",
        "Teach the importer what is and isn't a purchase order, and what's a revision "
        "of what. Every decision is enforced on the next run, fed back as a few-shot "
        "example, and used to block regressions in CI.",
    )

    queue = load_review_queue()
    reviews = load_extraction_reviews()
    candidates = load_revision_candidates()

    n_open = 0 if queue.empty else len(queue)
    n_stale = 0 if queue.empty else int(queue["stale"].sum())
    st.caption(
        f"{n_open} item(s) in the queue"
        + (f" · {n_stale} stale (content changed since the decision)" if n_stale else "")
        + f" · {len(reviews)} decision(s) recorded"
        + (f" · {len(candidates)} possible revision pair(s)" if not candidates.empty else "")
    )

    tab_q, tab_rev, tab_all = st.tabs(["Queue", "Possible revisions", "All decisions"])

    with tab_q:
        if queue.empty:
            st.success("Nothing flagged for review. New low-confidence extractions will show up here.")
        else:
            for _, row in queue.iterrows():
                _decision_form(ctx, row)

    with tab_rev:
        if candidates.empty:
            section_card(caption="No same-customer PO pairs sharing a delivery date with different PO numbers.")
        else:
            st.caption(
                "Same customer, same delivery date, different PO numbers — usually a revised PO for one "
                "order. Link the later one (B) as a revision of the earlier (A) where that's right."
            )
            for _, c in candidates.iterrows():
                cols = st.columns([3, 2, 1])
                cols[0].write(
                    f"**{c['customer_name']}** — delivery {c['delivery_date']}  ·  "
                    f"A PO {c['a_po_number'] or '—'}  →  B PO {c['b_po_number'] or '—'}"
                )
                cols[1].caption(f"A: {c['a_key']}\n\nB: {c['b_key']}")
                if cols[2].button("B revises A", key=f"link_{c['a_po_id']}_{c['b_po_id']}"):
                    save_extraction_review(
                        target_kind=c["b_kind"], target_key=str(c["b_key"]), verdict="is_po",
                        revision_of=str(c["a_group_key"]), reviewer=_REVIEWER,
                        note=f"linked as revision of PO {c['a_po_number']} (delivery {c['delivery_date']})",
                    )
                    st.success("Linked.")
                    st.rerun()

    with tab_all:
        if reviews.empty:
            section_card(caption="No decisions recorded yet.")
        else:
            show = reviews.copy()
            show["standalone"] = show["standalone"].map({True: "✓", False: ""})
            data_grid(
                show, ["target_kind", "target_key", "verdict", "revision_of", "standalone",
                       "note", "reviewer", "updated_at"],
                key="all_reviews_grid",
            )
            with st.form("delete_review"):
                to_del = st.selectbox(
                    "Remove a decision (reverts that target to normal extraction)",
                    options=["—"] + [f"{r.target_kind}:{r.target_key}" for r in reviews.itertuples()],
                )
                if st.form_submit_button("Delete") and to_del != "—":
                    k, v = to_del.split(":", 1)
                    delete_extraction_review(k, v)
                    st.success("Removed.")
                    st.rerun()
