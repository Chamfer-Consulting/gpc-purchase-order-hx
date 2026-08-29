"""Admin CRUD for purchase orders: create from scratch, lifecycle status changes,
soft delete / restore, per-line void, revision regrouping, and manual PO<->invoice
linking. Every mutation:
  * writes an audit_log row (services/audit.py), and
  * stamps the PO edited = TRUE / edited_by / edited_at, which is the guard
    sync_dashboard.py already honours — so a non-active or admin-touched PO is
    never overwritten or resurrected by the extraction pipeline.

psycopg2 connections (reused_conn), same as po_edit / the reused repo modules."""

import uuid

import psycopg2.extras

import extraction_reviews  # repo root, via app.reuse
import qbo_client  # dashboard/, via app.reuse
import qbo_matcher  # dashboard/, via app.reuse
from math_check import validate_math  # repo root, via app.reuse

from . import audit
from .po_edit import _insert_line, _jsonify, get_po

VALID_STATUS = ("active", "draft", "cancelled", "withdrawn", "voided", "deleted")
_NON_ACTIVE = tuple(s for s in VALID_STATUS if s != "active")

# status -> audit action verb
_STATUS_ACTION = {"deleted": "delete", "active": "restore"}


class AdminError(ValueError):
    """Bad request from the admin surface (404 / 409 / 422 at the router)."""


# --------------------------------------------------------------------------- read


def _header_row(cur, po_id: int) -> dict | None:
    cur.execute(
        """
        SELECT id, po_number, customer_name, customer_id, status, status_reason,
               status_at, deleted_at, edited, edited_by, source_file, gmail_thread_id,
               delivery_date, po_date, subtotal, tax, total
        FROM purchase_orders WHERE id = %s
        """,
        (po_id,),
    )
    row = cur.fetchone()
    return _jsonify(dict(row)) if row else None


def _target(source_file: str | None, thread_id: str | None) -> tuple[str, str]:
    if (source_file or "").startswith("gmail-thread:") and thread_id:
        return "thread", thread_id
    return "file", source_file or ""


def po_detail(conn, po_id: int) -> dict | None:
    """get_po() (header + items + removed_items) plus the admin extras: lifecycle
    status, the revision chain, invoice links, and the audit trail."""
    base = get_po(conn, po_id)
    if base is None:
        return None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        hdr = _header_row(cur, po_id)
        base["header"].update(
            {
                "status": hdr["status"],
                "status_reason": hdr["status_reason"],
                "status_at": hdr["status_at"],
                "deleted_at": hdr["deleted_at"],
                "customer_id": hdr["customer_id"],
            }
        )
        base["revisions"] = _revision_chain(cur, hdr)
        base["links"] = _links(cur, po_id)
        base["sources"] = _sources(cur, hdr)
    base["audit"] = audit.history(conn, "purchase_order", po_id)
    return base


def _sources(cur, hdr: dict) -> dict:
    """Deep link back to where this PO originally came from. The PO/invoice PDFs
    themselves are captured into po_documents (see services/po_docs.py)."""
    out: dict = {"gmail_thread_url": None}
    if hdr.get("gmail_thread_id"):
        cur.execute(
            "SELECT url FROM gmail_thread_meta WHERE thread_id = %s", (hdr["gmail_thread_id"],)
        )
        row = cur.fetchone()
        out["gmail_thread_url"] = row["url"] if row else None
    return out


def _revision_chain(cur, hdr: dict) -> list[dict]:
    """Sibling POs — same customer + same delivery date, or the same PO number."""
    cur.execute(
        """
        SELECT id AS po_id, po_number, customer_name, po_date, delivery_date,
               is_revision, revision_label, status, total, source_file
        FROM purchase_orders
        WHERE id <> %(id)s
          AND (
            (customer_name IS NOT DISTINCT FROM %(customer)s
             AND delivery_date IS NOT DISTINCT FROM %(delivery)s
             AND %(delivery)s IS NOT NULL)
            OR (po_number IS NOT DISTINCT FROM %(po_number)s AND %(po_number)s IS NOT NULL)
          )
        ORDER BY po_date NULLS LAST, id
        """,
        {
            "id": hdr["id"],
            "customer": hdr["customer_name"],
            "delivery": hdr["delivery_date"],
            "po_number": hdr["po_number"],
        },
    )
    return [_jsonify(dict(r)) for r in cur.fetchall()]


def _links(cur, po_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT l.invoice_id, l.match_method, l.match_score, l.confirmed, l.rejected,
               l.linked_at, i.doc_number, i.txn_date, i.total_amt, i.customer_name,
               i.qbo_invoice_id
        FROM po_invoice_links l
        JOIN qbo_invoices i ON i.id = l.invoice_id
        WHERE l.po_id = %s
        ORDER BY l.confirmed DESC, l.rejected, l.linked_at
        """,
        (po_id,),
    )
    out = []
    for r in cur.fetchall():
        d = _jsonify(dict(r))
        d["qbo_url"] = qbo_client.invoice_url(r["qbo_invoice_id"]) if r["qbo_invoice_id"] else None
        out.append(d)
    return out


_ARCHIVE_COLS = """
    po.id AS po_id, po.po_number, po.customer_name, po.po_date, po.delivery_date,
    po.status, po.status_reason, po.status_at, po.deleted_at, po.total,
    po.source_file, po.edited_by,
    (SELECT count(*) FROM line_items li WHERE li.po_id = po.id AND NOT li.is_removed) AS n_items
"""


def list_inactive(conn, status: str | None = None, limit: int = 500) -> list[dict]:
    """Every PO whose status isn't 'active' (or just one status bucket), newest
    status change first — the archive tab's data source."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if status and status != "all":
            if status not in VALID_STATUS:
                raise AdminError(f"unknown status {status!r}")
            cur.execute(
                f"SELECT {_ARCHIVE_COLS} FROM purchase_orders po WHERE po.status = %s "
                "ORDER BY po.status_at DESC NULLS LAST, po.id DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                f"SELECT {_ARCHIVE_COLS} FROM purchase_orders po WHERE po.status <> 'active' "
                "ORDER BY po.status_at DESC NULLS LAST, po.id DESC LIMIT %s",
                (limit,),
            )
        return [_jsonify(dict(r)) for r in cur.fetchall()]


def inactive_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) FROM purchase_orders "
            "WHERE status <> 'active' GROUP BY status"
        )
        counts = {row[0]: row[1] for row in cur.fetchall()}
    counts["all"] = sum(counts.values())
    return counts


def search_invoices(conn, q: str | None, limit: int = 25) -> list[dict]:
    like = f"%{(q or '').strip()}%"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT i.id AS invoice_id, i.doc_number, i.txn_date, i.total_amt,
                   i.customer_name,
                   EXISTS (SELECT 1 FROM po_invoice_links l
                           WHERE l.invoice_id = i.id AND l.confirmed) AS linked
            FROM qbo_invoices i
            WHERE %(q)s = '' OR i.doc_number ILIKE %(like)s OR i.customer_name ILIKE %(like)s
            ORDER BY i.txn_date DESC NULLS LAST, i.id DESC
            LIMIT %(limit)s
            """,
            {"q": (q or "").strip(), "like": like, "limit": limit},
        )
        return [_jsonify(dict(r)) for r in cur.fetchall()]


# -------------------------------------------------------------------------- write


def _stamp_edited(cur, po_id: int, actor: str | None) -> None:
    cur.execute(
        "UPDATE purchase_orders SET edited = TRUE, edited_by = %s, edited_at = now() "
        "WHERE id = %s",
        (actor, po_id),
    )


def create_po(conn, actor: str | None, header: dict, items: list[dict]) -> int:
    """A PO typed in by hand (phone order, walk-in). source_file is a synthetic
    'manual:<uuid>' so it never collides with a real ingested file."""
    token = f"manual:{uuid.uuid4()}"
    payload = {
        "subtotal": header.get("subtotal"),
        "tax": header.get("tax"),
        "total": header.get("total"),
        "line_items": items,
    }
    validate_math(payload)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO purchase_orders (
                source_file, file_hash, extraction_method, po_number, po_date,
                delivery_date, customer_name, customer_id, subtotal, tax, total, notes,
                math_check_failed, math_check_detail, status, edited, edited_by, edited_at,
                extracted_at
            ) VALUES (
                %(sf)s, %(fh)s, 'manual', %(po_number)s, %(po_date)s, %(delivery_date)s,
                %(customer_name)s, %(customer_id)s, %(subtotal)s, %(tax)s, %(total)s, %(notes)s,
                %(mcf)s, %(mcd)s, 'active', TRUE, %(actor)s, now(), now()
            ) RETURNING id
            """,
            {
                "sf": token, "fh": token,
                "po_number": header.get("po_number"),
                "po_date": header.get("po_date") or None,
                "delivery_date": header.get("delivery_date") or None,
                "customer_name": header.get("customer_name"),
                "customer_id": header.get("customer_id"),
                "subtotal": header.get("subtotal"),
                "tax": header.get("tax"),
                "total": header.get("total"),
                "notes": header.get("notes"),
                "mcf": payload["math_check_failed"],
                "mcd": payload["math_check_detail"],
                "actor": actor,
            },
        )
        po_id = cur.fetchone()[0]
        for it in items:
            _insert_line(cur, po_id, it, removed=False)
        audit.log(conn, actor=actor, action="create", entity="purchase_order",
                  entity_id=po_id, before=None,
                  after={"source_file": token, "customer_name": header.get("customer_name"),
                         "po_number": header.get("po_number"), "n_items": len(items)})
    conn.commit()
    return po_id


def set_status(conn, actor: str | None, po_id: int, status: str,
               reason: str | None = None) -> dict:
    if status not in VALID_STATUS:
        raise AdminError(f"unknown status {status!r}")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        before = _header_row(cur, po_id)
        if before is None:
            raise AdminError("PO not found")
        cur.execute(
            """
            UPDATE purchase_orders SET
                status = %(status)s,
                status_reason = %(reason)s,
                status_at = now(),
                deleted_at = CASE WHEN %(status)s = 'deleted' THEN now() ELSE NULL END
            WHERE id = %(id)s
            """,
            {"status": status, "reason": reason, "id": po_id},
        )
        _stamp_edited(cur, po_id, actor)
        after = _header_row(cur, po_id)
        action = _STATUS_ACTION.get(status, "status")
        audit.log(conn, actor=actor, action=action, entity="purchase_order",
                  entity_id=po_id,
                  before={"status": before["status"], "status_reason": before["status_reason"]},
                  after={"status": status, "status_reason": reason})
    conn.commit()
    return after


def bulk_set_status(conn, actor: str | None, po_ids: list[int], status: str,
                    reason: str | None = None) -> dict:
    """Apply one status to many POs. Commits per PO (via set_status) so a bad id
    partway through doesn't roll back the rest. Returns per-id outcomes."""
    if status not in VALID_STATUS:
        raise AdminError(f"unknown status {status!r}")
    done: list[int] = []
    failed: list[dict] = []
    for po_id in dict.fromkeys(po_ids):  # de-dupe, keep order
        try:
            set_status(conn, actor, po_id, status, reason)
            done.append(po_id)
        except AdminError as exc:
            conn.rollback()
            failed.append({"po_id": po_id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — record and continue the batch
            conn.rollback()
            failed.append({"po_id": po_id, "error": str(exc)})
    return {"status": status, "updated": done, "failed": failed}


def void_line(conn, actor: str | None, po_id: int, line_id: int,
              voided: bool, reason: str | None = None) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, po_id, product_name, quantity, line_total, voided, void_reason "
            "FROM line_items WHERE id = %s AND po_id = %s",
            (line_id, po_id),
        )
        before = cur.fetchone()
        if before is None:
            raise AdminError("line item not found on this PO")
        cur.execute(
            "UPDATE line_items SET voided = %s, void_reason = %s WHERE id = %s",
            (voided, reason if voided else None, line_id),
        )
        _stamp_edited(cur, po_id, actor)
        audit.log(conn, actor=actor, action="line_void", entity="purchase_order",
                  entity_id=po_id,
                  before={"line_id": line_id, "product": before["product_name"],
                          "voided": before["voided"], "void_reason": before["void_reason"]},
                  after={"line_id": line_id, "voided": voided,
                         "void_reason": reason if voided else None})
        cur.execute(
            "SELECT id, po_id, product_name, quantity, line_total, voided, void_reason "
            "FROM line_items WHERE id = %s",
            (line_id,),
        )
        out = _jsonify(dict(cur.fetchone()))
    conn.commit()
    return out


def set_customer(conn, actor: str | None, po_id: int, customer_name: str | None,
                 customer_id: str | None = None) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        before = _header_row(cur, po_id)
        if before is None:
            raise AdminError("PO not found")
        cur.execute(
            "UPDATE purchase_orders SET customer_name = %s, customer_id = %s WHERE id = %s",
            (customer_name, customer_id, po_id),
        )
        _stamp_edited(cur, po_id, actor)
        audit.log(conn, actor=actor, action="customer", entity="purchase_order",
                  entity_id=po_id,
                  before={"customer_name": before["customer_name"],
                          "customer_id": before["customer_id"]},
                  after={"customer_name": customer_name, "customer_id": customer_id})
        out = _header_row(cur, po_id)
    conn.commit()
    return out


def regroup(conn, actor: str | None, po_id: int, revision_of: str | None = None,
            standalone: bool = False) -> dict:
    """Manual revision grouping. Writes an extraction_reviews decision keyed to this
    PO's thread/file; the pipeline's annotate_revisions honours revision_of
    (_group_override) and standalone (_standalone) on the next run."""
    if revision_of and standalone:
        raise AdminError("pass revision_of or standalone, not both")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_file, gmail_thread_id FROM purchase_orders WHERE id = %s",
            (po_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AdminError("PO not found")
        kind, key = _target(row[0], row[1])
        _stamp_edited(cur, po_id, actor)
    # upsert_decision commits (flushing the edited stamp above with it)
    extraction_reviews.upsert_decision(
        conn, target_kind=kind, target_key=key, verdict="is_po",
        revision_of=revision_of or None, standalone=standalone,
        reviewer=actor, note="admin regroup",
    )
    audit.log(conn, actor=actor, action="revision", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"target_kind": kind, "target_key": key,
                     "revision_of": revision_of, "standalone": standalone})
    conn.commit()
    return {"target_kind": kind, "target_key": key, "revision_of": revision_of,
            "standalone": standalone}


def link_invoice(conn, actor: str | None, po_id: int, invoice_id: int,
                 replace_existing: bool = False) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM purchase_orders WHERE id = %s", (po_id,))
        if cur.fetchone() is None:
            raise AdminError("PO not found")
        cur.execute("SELECT 1 FROM qbo_invoices WHERE id = %s", (invoice_id,))
        if cur.fetchone() is None:
            raise AdminError("invoice not found")
    audit.log(conn, actor=actor, action="link", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"invoice_id": invoice_id, "replace_existing": replace_existing})
    # manual_link commits (audit row above rides along in the same transaction)
    qbo_matcher.manual_link(conn, po_id, invoice_id, replace_existing=replace_existing)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _links(cur, po_id)


def unlink_invoice(conn, actor: str | None, po_id: int, invoice_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "DELETE FROM po_invoice_links WHERE po_id = %s AND invoice_id = %s RETURNING match_method",
            (po_id, invoice_id),
        )
        gone = cur.fetchone()
        if gone is None:
            raise AdminError("no such link")
        audit.log(conn, actor=actor, action="unlink", entity="purchase_order",
                  entity_id=po_id,
                  before={"invoice_id": invoice_id, "match_method": gone["match_method"]},
                  after=None)
        links = _links(cur, po_id)
    conn.commit()
    return links
