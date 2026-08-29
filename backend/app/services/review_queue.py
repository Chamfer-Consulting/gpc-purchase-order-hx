"""Extraction review queue + revision candidates — the SQL-only slice of what
dashboard/data.py did with pandas. Kept here (not left as a stub) because it's a
plain query plus a small ranking loop, no dataframe machinery."""

import psycopg2.extras

_QUEUE_SQL = """
WITH li AS (
    SELECT po_id,
           count(*) FILTER (WHERE NOT is_removed) AS n_items,
           count(*) FILTER (WHERE math_mismatch IS NOT NULL AND NOT is_removed) AS n_math
    FROM line_items GROUP BY po_id
)
SELECT po.id AS po_id,
       po.gmail_thread_id, po.source_file, po.error, po.customer_name, po.po_date,
       COALESCE(li.n_items, 0) AS n_items,
       COALESCE(li.n_math, 0)  AS n_math,
       po.math_check_failed,
       m.subject, m.from_addrs, m.url AS gmail_url,
       r.verdict AS decided_verdict, r.content_hash AS decided_hash,
       s.content AS snapshot, s.content_hash AS snapshot_hash
FROM purchase_orders po
LEFT JOIN li ON li.po_id = po.id
LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
LEFT JOIN extraction_reviews r
       ON (r.target_kind = 'thread' AND r.target_key = po.gmail_thread_id)
       OR (r.target_kind = 'file'   AND r.target_key = po.source_file)
LEFT JOIN extraction_snapshots s
       ON (s.target_kind = 'thread' AND s.target_key = po.gmail_thread_id)
       OR (s.target_kind = 'file'   AND s.target_key = po.source_file)
WHERE po.gmail_thread_id IS NOT NULL
  AND po.status = 'active'
"""


def _target(row: dict) -> tuple[str, str]:
    if (row["source_file"] or "").startswith("gmail-thread:") and row["gmail_thread_id"]:
        return "thread", row["gmail_thread_id"]
    return "file", row["source_file"]


def review_queue(conn, limit: int = 300) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_QUEUE_SQL)
        rows = [dict(r) for r in cur.fetchall()]

    # The extraction_reviews / extraction_snapshots joins are ON (thread) OR (file);
    # if a PO ever matches under both keyings it fans out to >1 row. Keep the first
    # per po_id so the queue + the needs-attention counts never double.
    seen: set[int] = set()
    rows = [r for r in rows if not (r["po_id"] in seen or seen.add(r["po_id"]))]

    out = []
    for r in rows:
        kind, key = _target(r)
        decided = r["decided_verdict"] is not None
        stale = bool(decided and r["decided_hash"] and r["decided_hash"] != r["snapshot_hash"])
        clean = not r["error"]
        err = str(r["error"] or "")

        why, prio = [], 0
        if err.startswith("modification"):
            why.append("unresolved modification — link it to a PO"); prio += 7
        if clean and r["n_items"] == 0:
            why.append("0 line items"); prio += 5
        if clean and not r["customer_name"]:
            why.append("no customer"); prio += 3
        if r["n_math"] or r["math_check_failed"]:
            why.append("math mismatch"); prio += 4
        if stale:
            why.append("decision is stale (content changed)"); prio += 6

        if prio == 0 or (decided and not stale):
            continue

        out.append({
            "po_id": r["po_id"],
            "target_kind": kind,
            "target_key": key,
            "reason": ", ".join(why),
            "priority": prio,
            "customer_name": r["customer_name"],
            "po_date": r["po_date"].isoformat() if r["po_date"] else None,
            "n_items": r["n_items"],
            "error": r["error"],
            "subject": r["subject"],
            "from_addrs": r["from_addrs"],
            "gmail_url": r["gmail_url"],
            "snapshot": r["snapshot"],
            "decided": decided,
            "stale": stale,
        })

    out.sort(key=lambda x: x["po_date"] or "", reverse=True)
    out.sort(key=lambda x: x["priority"], reverse=True)  # stable — priority first, then newest
    return out[:limit]


def revision_candidates(conn, limit: int = 150) -> list[dict]:
    """Same customer + same delivery_date + different PO number, not already grouped
    and not already decided."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id AS po_id, customer_name, delivery_date, po_date, po_number,
                   is_revision, source_file, gmail_thread_id
            FROM purchase_orders
            WHERE (error IS NULL OR error = '')
              AND status = 'active'
              AND customer_name IS NOT NULL AND delivery_date IS NOT NULL
              AND delivery_date > (now() - interval '18 months')
            ORDER BY customer_name, delivery_date, po_date
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT target_kind, target_key FROM extraction_reviews")
        decided = {(r["target_kind"], r["target_key"]) for r in cur.fetchall()}

    def tgt(r):
        return _target(r)

    out = []
    from itertools import groupby

    for (_cust, _dd), grp in groupby(rows, key=lambda r: (r["customer_name"], r["delivery_date"])):
        recs = list(grp)
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                if (a["po_number"] or "") == (b["po_number"] or ""):
                    continue
                if a["is_revision"] and b["is_revision"]:
                    continue
                if tgt(b) in decided:
                    continue
                out.append({
                    "a_po_id": a["po_id"], "b_po_id": b["po_id"], "customer_name": a["customer_name"],
                    "delivery_date": a["delivery_date"].isoformat() if a["delivery_date"] else None,
                    "a_po_number": a["po_number"], "b_po_number": b["po_number"],
                    "a_group_key": a["po_number"] or a["source_file"],
                    "b_kind": tgt(b)[0], "b_key": tgt(b)[1],
                })
    return out[:limit]
