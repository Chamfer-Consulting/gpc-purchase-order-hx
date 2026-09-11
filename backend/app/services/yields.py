"""Product Yields — harvest logging, a domain separate from PO/QBO sales.

yield_products is a standalone crop/variety catalog. yield_entries are harvest
log rows (weight + tray counts); multiple entries per product per day are
expected, so there's no daily-uniqueness constraint. harvested_by is the
individual worker (free text — the kiosk login is shared across workers, not
per-employee); submitted_by is the signed-in kiosk account's email, an audit
trail rather than the worker's identity.

A 'field'-rank caller (the harvest kiosk role) may only edit/void its own
same-day entries; every other role is unrestricted — see _assert_can_touch.
Product/SKU-link management and trend rollups land in a later phase; see
supabase/migrations/0014_yields.sql.
"""

from __future__ import annotations

from datetime import date as _date

import psycopg2.errors
import psycopg2.extras
from business_tz import business_now  # shared/, via app.reuse

from ..errors import Forbidden, InUse, NotFound
from . import audit

# --- products ----------------------------------------------------------------


def list_products(conn, *, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else "WHERE active"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT id, name, active, notes FROM yield_products {where} ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


def create_product(conn, name: str, notes: str | None = None, *, actor: str | None = None) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_products (name, notes) VALUES (%s, %s) "
            "RETURNING id, name, active, notes",
            (name.strip(), notes),
        )
        row = dict(cur.fetchone())
    audit.log(conn, actor=actor, action="create", entity="yield_product", entity_id=row["id"], after=row)
    conn.commit()
    return row


def update_product(conn, product_id: int, *, name: str | None = None, active: bool | None = None,
                    notes: str | None = None, actor: str | None = None) -> dict:
    sets: list[str] = []
    vals: list[object] = []
    if name is not None:
        sets.append("name = %s")
        vals.append(name.strip())
    if active is not None:
        sets.append("active = %s")
        vals.append(active)
    if notes is not None:
        sets.append("notes = %s")
        vals.append(notes)
    if not sets:
        raise ValueError("nothing to update")
    sets.append("updated_at = now()")
    vals.append(product_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"UPDATE yield_products SET {', '.join(sets)} WHERE id = %s "
            "RETURNING id, name, active, notes",
            vals,
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound(f"yield product {product_id} not found")
        row = dict(row)
    audit.log(conn, actor=actor, action="edit", entity="yield_product", entity_id=product_id, after=row)
    conn.commit()
    return row


def delete_product(conn, product_id: int, *, actor: str | None = None) -> None:
    """Hard delete — only succeeds while nothing references this product yet
    (yield_entries.yield_product_id is ON DELETE RESTRICT). Once a harvest has
    been logged against it, retire it instead (update_product(active=False))."""
    with conn.cursor() as cur:
        try:
            cur.execute("DELETE FROM yield_products WHERE id = %s", (product_id,))
        except psycopg2.errors.ForeignKeyViolation as exc:
            raise InUse(
                "This product has harvest entries on record — retire it instead of deleting it."
            ) from exc
        gone = cur.rowcount
    if not gone:
        raise NotFound(f"yield product {product_id} not found")
    audit.log(conn, actor=actor, action="delete", entity="yield_product", entity_id=product_id)
    conn.commit()


# --- entries -------------------------------------------------------------


def _entry_row(r: dict) -> dict:
    return {
        **r,
        "harvest_date": r["harvest_date"].isoformat() if r.get("harvest_date") else None,
        "weight": float(r["weight"]) if r.get("weight") is not None else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def create_entry(conn, *, yield_product_id: int, harvest_date: _date, weight: float, unit: str,
                  tray_count: int = 0, discarded_tray_count: int = 0,
                  storage_bin: str | None = None, lot_code: str | None = None,
                  harvested_by: str, notes: str | None = None, submitted_by: str) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO yield_entries
                (yield_product_id, harvest_date, weight, unit, tray_count,
                 discarded_tray_count, storage_bin, lot_code, harvested_by, notes, submitted_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (yield_product_id, harvest_date, weight, unit, tray_count, discarded_tray_count,
             storage_bin, lot_code, harvested_by, notes, submitted_by),
        )
        row = _entry_row(dict(cur.fetchone()))
    audit.log(conn, actor=submitted_by, action="create", entity="yield_entry",
              entity_id=row["id"], after=row)
    conn.commit()
    return row


def list_entries(conn, *, yield_product_id: int | None = None, date_from: _date | None = None,
                  date_to: _date | None = None, harvested_by: str | None = None,
                  submitted_by: str | None = None, include_voided: bool = False) -> list[dict]:
    where: list[str] = [] if include_voided else ["NOT e.voided"]
    vals: list[object] = []
    if yield_product_id is not None:
        where.append("e.yield_product_id = %s")
        vals.append(yield_product_id)
    if date_from is not None:
        where.append("e.harvest_date >= %s")
        vals.append(date_from)
    if date_to is not None:
        where.append("e.harvest_date <= %s")
        vals.append(date_to)
    if harvested_by:
        where.append("e.harvested_by = %s")
        vals.append(harvested_by)
    if submitted_by:
        where.append("e.submitted_by = %s")
        vals.append(submitted_by)
    sql = "SELECT e.*, p.name AS product_name FROM yield_entries e JOIN yield_products p ON p.id = e.yield_product_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.harvest_date DESC, e.created_at DESC"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, vals)
        return [_entry_row(dict(r)) for r in cur.fetchall()]


def _assert_can_touch(conn, entry_id: int, *, actor: str | None, actor_role: str) -> dict:
    """A 'field'-rank caller may only touch its own same-day entries; every
    other role (viewer and up) is unrestricted — Yields isn't the sensitive
    domain the 'field' floor exists to protect, PO/financial data is."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM yield_entries WHERE id = %s", (entry_id,))
        row = cur.fetchone()
    if row is None:
        raise NotFound(f"yield entry {entry_id} not found")
    row = dict(row)
    if actor_role == "field":
        same_day = row["harvest_date"] == business_now().date()
        own = (row["submitted_by"] or "").lower() == (actor or "").lower()
        if not (same_day and own):
            raise Forbidden(need="editor", have=actor_role)
    return row


_ENTRY_PATCH_FIELDS = {
    "weight", "unit", "tray_count", "discarded_tray_count", "storage_bin",
    "lot_code", "harvested_by", "notes", "harvest_date",
}


def update_entry(conn, entry_id: int, patch: dict, *, actor: str | None, actor_role: str) -> dict:
    _assert_can_touch(conn, entry_id, actor=actor, actor_role=actor_role)
    sets: list[str] = []
    vals: list[object] = []
    for k, v in patch.items():
        if k in _ENTRY_PATCH_FIELDS and v is not None:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        raise ValueError("nothing to update")
    sets.append("updated_at = now()")
    vals.append(entry_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"UPDATE yield_entries SET {', '.join(sets)} WHERE id = %s RETURNING *", vals)
        row = _entry_row(dict(cur.fetchone()))
    audit.log(conn, actor=actor, action="edit", entity="yield_entry", entity_id=entry_id, after=row)
    conn.commit()
    return row


def void_entry(conn, entry_id: int, reason: str | None, *, actor: str | None, actor_role: str) -> dict:
    _assert_can_touch(conn, entry_id, actor=actor, actor_role=actor_role)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE yield_entries SET voided = TRUE, void_reason = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (reason, entry_id),
        )
        row = _entry_row(dict(cur.fetchone()))
    audit.log(conn, actor=actor, action="void", entity="yield_entry", entity_id=entry_id, after=row)
    conn.commit()
    return row


# --- notes -----------------------------------------------------------------


def _note_row(r: dict) -> dict:
    return {
        **r,
        "note_date": r["note_date"].isoformat() if r.get("note_date") else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


def list_notes(conn, *, yield_product_id: int | None = None) -> list[dict]:
    where: list[str] = []
    vals: list[object] = []
    if yield_product_id is not None:
        where.append("n.yield_product_id = %s")
        vals.append(yield_product_id)
    sql = ("SELECT n.*, p.name AS product_name FROM yield_notes n "
           "LEFT JOIN yield_products p ON p.id = n.yield_product_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY n.note_date DESC, n.created_at DESC"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, vals)
        return [_note_row(dict(r)) for r in cur.fetchall()]


def create_note(conn, *, yield_product_id: int | None, note: str, note_date: _date | None = None,
                 submitted_by: str) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_notes (yield_product_id, note, note_date, submitted_by) "
            "VALUES (%s, %s, COALESCE(%s, CURRENT_DATE), %s) RETURNING *",
            (yield_product_id, note, note_date, submitted_by),
        )
        row = _note_row(dict(cur.fetchone()))
    conn.commit()
    return row


def delete_note(conn, note_id: int, *, actor: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yield_notes WHERE id = %s", (note_id,))
        gone = cur.rowcount
    if gone:
        audit.log(conn, actor=actor, action="delete", entity="yield_note", entity_id=note_id)
    conn.commit()
