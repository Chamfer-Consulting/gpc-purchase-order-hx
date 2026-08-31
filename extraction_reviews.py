"""
Human review decisions that OVERRIDE and TRAIN the PO extractor.

See the `extraction_reviews` table comment in schema.sql for the data model and
the three consumers. This module is deliberately dependency-free (only
psycopg2.extras, same as postgres_store.py / product_catalog.py) so it imports
cleanly under .venv312 for the cloud pipeline / GitHub Action AND from the
Streamlit dashboard.

A "target" is one of:
  - ("thread", "<gmail thread_id>")   — a whole conversational thread
  - ("file",   "<source_file>")       — one PDF attachment / local file

Verdicts:
  - "not_po"    : not a purchase order. Skips extraction entirely (no model call).
  - "is_po"     : it is a purchase order. If `corrected` is set, that payload is
                  published verbatim (no model call); otherwise the model still
                  extracts but its is_po=false is ignored.
  - "needs_fix" : it is a PO but the current extraction is wrong and no correction
                  has been supplied yet — treated as advisory (does NOT block the
                  model), surfaced in the review queue.
"""

import json

import psycopg2.extras

VERDICTS = ("is_po", "not_po", "needs_fix")

# content_snapshot is only for the eval replay + few-shot text — cap it so a
# pathological thread can't bloat the table or a prompt.
SNAPSHOT_MAX_CHARS = 20_000

_HEADER_KEYS = (
    "po_number", "po_date", "delivery_date", "sent_date", "customer_name",
    "customer_id", "subtotal", "tax", "total", "notes",
)


# ── read ──────────────────────────────────────────────────────────────────────

def get_decision(conn, target_kind: str, target_key: str) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM extraction_reviews WHERE target_kind = %s AND target_key = %s",
            (target_kind, target_key),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def all_decisions(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM extraction_reviews ORDER BY updated_at DESC")
        return [dict(r) for r in cur.fetchall()]


def group_override_map(conn) -> dict:
    """{ target_key : {"revision_of": ..., "standalone": bool} } for every decision
    that pins revision grouping. Applied to result dicts before annotate_revisions()
    so a human call on "is this a revision" is authoritative."""
    out = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT target_key, revision_of, standalone FROM extraction_reviews "
            "WHERE revision_of IS NOT NULL OR standalone = TRUE"
        )
        for r in cur.fetchall():
            out[r["target_key"]] = {"revision_of": r["revision_of"], "standalone": r["standalone"]}
    return out


# ── write ─────────────────────────────────────────────────────────────────────

def upsert_decision(
    conn,
    *,
    target_kind: str,
    target_key: str,
    verdict: str,
    content_hash: str | None = None,
    content_snapshot: str | None = None,
    revision_of: str | None = None,
    standalone: bool = False,
    corrected: dict | None = None,
    fewshot: bool = True,
    reviewer: str | None = None,
    note: str | None = None,
    commit: bool = True,
) -> None:
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r} (expected one of {VERDICTS})")
    if revision_of and standalone:
        raise ValueError("a decision cannot be both revision_of=<x> and standalone")
    snap = (content_snapshot or "")[:SNAPSHOT_MAX_CHARS] or None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extraction_reviews
                (target_kind, target_key, content_hash, content_snapshot, verdict,
                 revision_of, standalone, corrected, fewshot, reviewer, note, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (target_kind, target_key) DO UPDATE SET
                content_hash     = EXCLUDED.content_hash,
                -- keep an existing snapshot if this update didn't carry a new one
                content_snapshot = COALESCE(EXCLUDED.content_snapshot, extraction_reviews.content_snapshot),
                verdict          = EXCLUDED.verdict,
                revision_of      = EXCLUDED.revision_of,
                standalone       = EXCLUDED.standalone,
                corrected        = EXCLUDED.corrected,
                fewshot          = EXCLUDED.fewshot,
                reviewer         = EXCLUDED.reviewer,
                note             = EXCLUDED.note,
                updated_at       = now()
            """,
            (
                target_kind, target_key, content_hash, snap, verdict,
                revision_of, standalone,
                json.dumps(corrected) if corrected is not None else None,
                fewshot, reviewer, note,
            ),
        )
    if commit:
        conn.commit()


def delete_decision(conn, target_kind: str, target_key: str, commit: bool = True) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM extraction_reviews WHERE target_kind = %s AND target_key = %s",
            (target_kind, target_key),
        )
    if commit:
        conn.commit()


# ── apply ─────────────────────────────────────────────────────────────────────

def is_stale(decision: dict, current_hash: str | None) -> bool:
    """True when the decision was made on different content than what's in front of
    the pipeline now — the override then becomes advisory only."""
    return (
        bool(decision.get("content_hash"))
        and current_hash is not None
        and decision["content_hash"] != current_hash
    )


def _corrected_dict(decision: dict) -> dict:
    c = decision.get("corrected")
    if c is None:
        return {}
    return json.loads(c) if isinstance(c, str) else dict(c)


def has_authoritative_result(decision: dict) -> bool:
    """True when the decision alone determines the row — no model call needed:
    a 'not_po' verdict, or an 'is_po' verdict that carries a corrected payload."""
    return decision["verdict"] == "not_po" or (
        decision["verdict"] == "is_po" and bool(_corrected_dict(decision))
    )


def wants_modification_extract(decision: dict) -> bool:
    """True when a reviewer said 'this thread is a revision of <PO>' without
    supplying the corrected line items — the pipeline should re-extract the thread
    as a modification seeded with that PO's current state, and group it there."""
    return (
        decision["verdict"] == "is_po"
        and bool(decision.get("revision_of"))
        and not _corrected_dict(decision)
    )


def synthesized_result(decision: dict, source_label: str, extraction_method: str) -> dict:
    """Build an extraction-result dict straight from the reviewer's decision, for
    the cases has_authoritative_result() covers. `_review_locked` marks it so the
    publish step protects it from a later model run (same intent as
    purchase_orders.edited)."""
    if decision["verdict"] == "not_po":
        return {
            "_source_file": source_label,
            "_extraction_method": extraction_method,
            "error": "not a purchase order",
            "_review_locked": True,
        }

    c = _corrected_dict(decision)
    result = {
        "_source_file": source_label,
        "_extraction_method": extraction_method,
        "_review_locked": True,
        "line_items": c.get("line_items") or [],
    }
    for k in _HEADER_KEYS:
        result[k] = c.get(k)
    return result


def apply_group_override(result: dict, override: dict) -> None:
    """Stamp a revision-grouping override onto a result dict in place, for
    annotate_revisions() to honour. See extract_pos.annotate_revisions."""
    if override.get("standalone"):
        result["_standalone"] = True
    elif override.get("revision_of"):
        result["_group_override"] = override["revision_of"]


# ── few-shot ─────────────────────────────────────────────────────────────────

def build_fewshot_block(
    conn, limit: int = 12, max_chars: int = 6_000, exclude: set | None = None
) -> str:
    """A compact block of verified examples for the extraction / gate prompts.
    Newest decisions first (they reflect the most recent corrections). Returns ""
    when there's nothing to show yet. `exclude` is a set of (target_kind,
    target_key) tuples to leave out — the eval passes the row under test so it
    can't see its own answer."""
    exclude = exclude or set()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT target_kind, target_key, verdict, revision_of, standalone, content_snapshot, note
            FROM extraction_reviews
            WHERE fewshot = TRUE AND content_snapshot IS NOT NULL AND content_snapshot <> ''
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit + len(exclude),),
        )
        rows = [dict(r) for r in cur.fetchall()
                if (r["target_kind"], r["target_key"]) not in exclude][:limit]
    if not rows:
        return ""

    lines = [
        "VERIFIED EXAMPLES from human review — learn the boundary between a real "
        "purchase order and other correspondence, and between a standalone PO and a "
        "revision. Do not quote these back; they are guidance only."
    ]
    for r in rows:
        if r["verdict"] == "not_po":
            label = "NOT a purchase order"
        elif r.get("revision_of"):
            label = f"purchase order — a REVISION of {r['revision_of']}"
        elif r.get("standalone"):
            label = "purchase order — STANDALONE (not a revision of anything)"
        else:
            label = "purchase order"
        excerpt = " ".join((r.get("content_snapshot") or "").split())[:400]
        line = f"- [{label}] {excerpt}"
        if r.get("note"):
            line += f"  — reviewer note: {' '.join(r['note'].split())[:160]}"
        lines.append(line)

    return "\n".join(lines)[:max_chars]
