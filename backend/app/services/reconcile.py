"""The unified reconciliation surface: one work queue and one per-PO view that
walks a purchase order through extraction correctness -> lifecycle -> invoice
match. Composes the existing pieces (review_queue, qbo_matcher, po_admin) — no new
business logic, just one shape for the /reconcile screen.
"""

import re

import psycopg2.extras

import qbo_client  # shared/, via app.reuse
import qbo_matcher  # shared/, via app.reuse

from . import po_admin, review_queue

_QTY_TOL = 0.001
_PRICE_TOL = 0.01
_TOTAL_TOL = 0.02

_STAGE_RANK = {"extraction": 0, "lifecycle": 1, "match": 2}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(product: str | None, size: str | None) -> str:
    p = re.sub(r"[^a-z0-9]+", " ", (product or "").lower()).strip()
    s = re.sub(r"[^a-z0-9]+", "", (size or "").lower())
    return f"{p}|{s}"


def _side(it: dict) -> dict:
    return {
        "quantity": _num(it.get("quantity")),
        "unit_price": _num(it.get("unit_price")),
        "line_total": _num(it.get("line_total")),
        "product_name": it.get("product_name"),
        "container_size": it.get("container_size"),
    }


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 4)


def _classify(po: dict | None, inv: dict | None) -> tuple[str, dict]:
    if po and not inv:
        return "po_only", {}
    if inv and not po:
        return "inv_only", {}
    d = {
        "quantity": _delta(po["quantity"], inv["quantity"]),
        "unit_price": _delta(po["unit_price"], inv["unit_price"]),
        "line_total": _delta(po["line_total"], inv["line_total"]),
    }
    if d["line_total"] is not None and abs(d["line_total"]) > _TOTAL_TOL:
        return "total_diff", d
    if d["quantity"] is not None and abs(d["quantity"]) > _QTY_TOL:
        return "qty_diff", d
    if d["unit_price"] is not None and abs(d["unit_price"]) > _PRICE_TOL:
        return "price_diff", d
    return "match", d


def line_diff(po_items: list[dict], inv_items: list[dict]) -> dict:
    """Align PO lines to invoice lines by normalised product+size and classify each
    row match | qty_diff | price_diff | total_diff | po_only | inv_only."""
    po_by: dict[str, list[dict]] = {}
    inv_by: dict[str, list[dict]] = {}
    for it in po_items:
        po_by.setdefault(_norm(it.get("product_name"), it.get("container_size")), []).append(_side(it))
    for it in inv_items:
        inv_by.setdefault(_norm(it.get("product_name"), it.get("container_size")), []).append(_side(it))

    rows = []
    for key in list(dict.fromkeys([*po_by, *inv_by])):
        ps, iv = po_by.get(key, []), inv_by.get(key, [])
        for i in range(max(len(ps), len(iv))):
            p = ps[i] if i < len(ps) else None
            n = iv[i] if i < len(iv) else None
            status, deltas = _classify(p, n)
            rows.append({
                "product": (p or n)["product_name"],
                "size": (p or n)["container_size"],
                "po": p,
                "inv": n,
                "status": status,
                "deltas": deltas,
            })

    po_total = sum(r["po"]["line_total"] for r in rows if r["po"] and r["po"]["line_total"] is not None)
    inv_total = sum(r["inv"]["line_total"] for r in rows if r["inv"] and r["inv"]["line_total"] is not None)
    n_diff = sum(1 for r in rows if r["status"] not in ("match",))
    return {
        "rows": rows,
        "totals": {"po": round(po_total, 2), "inv": round(inv_total, 2),
                   "delta": round(inv_total - po_total, 2)},
        "n_rows": len(rows),
        "n_diff": n_diff,
        "clean": n_diff == 0,
    }


# --------------------------------------------------------------------- queue


def queue(conn) -> dict:
    """One ranked list: POs with an extraction issue and/or a pending invoice
    match. Each item carries its reasons and the earliest unresolved stage."""
    items: dict[int, dict] = {}

    def add(po_id: int, reason: str, stage: str, prio: float, **meta) -> None:
        it = items.get(po_id)
        if it is None:
            it = {"po_id": po_id, "reasons": [], "_stages": set(), "priority": 0.0}
            items[po_id] = it
        it["reasons"].append(reason)
        it["_stages"].add(stage)
        it["priority"] = max(it["priority"], prio)
        for k, v in meta.items():
            if it.get(k) in (None, ""):
                it[k] = v

    for r in review_queue.review_queue(conn):
        add(r["po_id"], r["reason"], "extraction", r["priority"] + 10.0,
            customer_name=r["customer_name"], po_date=r["po_date"], subject=r["subject"],
            target_kind=r["target_kind"], target_key=r["target_key"])

    by_po: dict[int, list[dict]] = {}
    for c in qbo_matcher.get_needs_review(conn):
        by_po.setdefault(c["po_id"], []).append(c)
    for po_id, cands in by_po.items():
        best = max((_num(c["match_score"]) or 0.0) for c in cands)
        label = f"{len(cands)} invoice candidate{'s' if len(cands) != 1 else ''} to review"
        add(po_id, label, "match", 5.0 + best,
            customer_name=cands[0].get("po_customer"),
            po_number=cands[0].get("po_number"),
            po_date=cands[0]["po_date"].isoformat() if cands[0].get("po_date") else None,
            n_candidates=len(cands))

    unlinked_no_candidate = 0
    for po in qbo_matcher.get_unlinked_pos(conn):
        if po["id"] not in items and po["id"] not in by_po:
            unlinked_no_candidate += 1

    out = []
    counts = {"extraction": 0, "match": 0}
    for it in items.values():
        stages = it.pop("_stages")
        it["stage"] = min(stages, key=lambda s: _STAGE_RANK[s])
        for s in stages:
            if s in counts:
                counts[s] += 1
        out.append(it)

    out.sort(key=lambda x: (x["priority"], x.get("po_date") or ""), reverse=True)
    return {
        "items": out[:400],
        "counts": {**counts, "total": len(out), "unlinked_no_candidate": unlinked_no_candidate},
    }


# ----------------------------------------------------------------- per-PO view


def _po_num_match(po_number, inv_po_number):
    """True/False when the invoice carries its own PO number, else None."""
    if not inv_po_number:
        return None
    return qbo_matcher.normalize_po_number(po_number) == qbo_matcher.normalize_po_number(inv_po_number)


def _invoice_meta(conn, inv_ids) -> dict[int, dict]:
    """Per-invoice QBO extras the Match stage needs: a deep link into QuickBooks'
    own UI and the PO number recorded on the invoice itself (QBO 'PO Number'
    custom field), so a reviewer can eyeball both sides without leaving the page."""
    ids = list(inv_ids)
    if not ids:
        return {}
    out: dict[int, dict] = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, qbo_invoice_id, raw_json FROM qbo_invoices WHERE id = ANY(%s)",
            (ids,),
        )
        for r in cur.fetchall():
            out[r["id"]] = {
                "qbo_url": qbo_client.invoice_url(r["qbo_invoice_id"]) if r["qbo_invoice_id"] else None,
                "inv_po_number": qbo_matcher._invoice_po_number(r["raw_json"] or {}),
            }
    return out


_EXTRACTION_SQL = """
SELECT s.content AS snapshot, s.content_hash AS snapshot_hash,
       r.verdict, r.revision_of, r.standalone, r.note, r.updated_at,
       m.url AS gmail_url, m.subject
FROM purchase_orders po
LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
LEFT JOIN extraction_reviews r
       ON (r.target_kind = 'thread' AND r.target_key = po.gmail_thread_id)
       OR (r.target_kind = 'file'   AND r.target_key = po.source_file)
LEFT JOIN extraction_snapshots s
       ON (s.target_kind = 'thread' AND s.target_key = po.gmail_thread_id)
       OR (s.target_kind = 'file'   AND s.target_key = po.source_file)
WHERE po.id = %s
LIMIT 1
"""


def _target(source_file: str | None, thread_id: str | None) -> tuple[str, str]:
    if (source_file or "").startswith("gmail-thread:") and thread_id:
        return "thread", thread_id
    return "file", source_file or ""


def po_view(conn, po_id: int) -> dict | None:
    base = po_admin.po_detail(conn, po_id)
    if base is None:
        return None
    hdr = base["header"]
    kind, key = _target(hdr.get("source_file"), hdr.get("gmail_thread_id"))

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_EXTRACTION_SQL, (po_id,))
        ext = cur.fetchone()
    base["extraction"] = {
        "target_kind": kind,
        "target_key": key,
        "snapshot": ext["snapshot"] if ext else None,
        "snapshot_hash": ext["snapshot_hash"] if ext else None,
        "gmail_url": ext["gmail_url"] if ext else None,
        "subject": ext["subject"] if ext else None,
        "verdict": ext["verdict"] if ext else None,
        "revision_of": ext["revision_of"] if ext else None,
        "standalone": ext["standalone"] if ext else False,
        "note": ext["note"] if ext else None,
        "decided_at": ext["updated_at"].isoformat() if ext and ext["updated_at"] else None,
    }

    po_items = base["items"]
    pending = [c for c in qbo_matcher.get_needs_review(conn) if c["po_id"] == po_id]
    link_inv_ids = [l["invoice_id"] for l in base.get("links", [])]
    inv_ids = sorted({*(c["invoice_id"] for c in pending), *link_inv_ids})
    _, inv_items_map = qbo_matcher.get_line_items_for_review(conn, [], inv_ids)
    inv_meta = _invoice_meta(conn, inv_ids)

    base["candidates"] = [
        {
            **c,
            "po_date": c["po_date"].isoformat() if c.get("po_date") else None,
            "txn_date": c["txn_date"].isoformat() if c.get("txn_date") else None,
            "confidence": qbo_matcher.confidence_label(c["match_method"], c["match_score"]),
            "quick": qbo_matcher.is_quick_confirm(
                qbo_matcher.confidence_label(c["match_method"], c["match_score"])
            ),
            "qbo_url": inv_meta.get(c["invoice_id"], {}).get("qbo_url"),
            "inv_po_number": inv_meta.get(c["invoice_id"], {}).get("inv_po_number"),
            "po_number_match": _po_num_match(
                c.get("po_number"), inv_meta.get(c["invoice_id"], {}).get("inv_po_number")
            ),
            "diff": line_diff(po_items, inv_items_map.get(c["invoice_id"], [])),
        }
        for c in pending
    ]
    for l in base.get("links", []):
        l["diff"] = line_diff(po_items, inv_items_map.get(l["invoice_id"], []))
        meta = inv_meta.get(l["invoice_id"], {})
        l["inv_po_number"] = meta.get("inv_po_number")
        l["po_number_match"] = _po_num_match(hdr.get("po_number"), meta.get("inv_po_number"))
        if not l.get("qbo_url"):
            l["qbo_url"] = meta.get("qbo_url")

    return base
