"""Product Yields — harvest logging, a domain separate from PO/QBO sales.

yield_products is a standalone crop/variety catalog. yield_entries are harvest
log rows (weight + tray counts); multiple entries per product per day are
expected, so there's no daily-uniqueness constraint. harvested_by is the
individual worker (free text — the kiosk login is shared across workers, not
per-employee); submitted_by is the signed-in kiosk account's email, an audit
trail rather than the worker's identity.

A 'field'-rank caller (the harvest kiosk role) may only edit/void its own
same-day entries; every other role is unrestricted — see _assert_can_touch.
Yield-product <-> sales-SKU mapping lands in a later phase; see
supabase/migrations/0014_yields.sql.
"""

from __future__ import annotations

from datetime import date as _date

import psycopg2.errors
import psycopg2.extras
from business_tz import business_now  # shared/, via app.reuse

from ..errors import Forbidden, InUse, NotFound
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope
from . import audit

# Every unit an entry can be recorded in, converted to ounces for aggregation
# (oz is the default/most granular unit here — see 0014_yields.sql). Trends
# always report weight in oz; a display-unit toggle is a nice-to-have, not v1.
_OZ_PER_UNIT = {"oz": 1.0, "lb": 16.0, "g": 0.0352739619}
GRAINS = ("week", "month", "quarter", "year")

# --- products ----------------------------------------------------------------


def list_products(conn, *, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else "WHERE active"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, name, active, notes, lot_code_prefix FROM yield_products {where} ORDER BY name",
        )
        return [dict(r) for r in cur.fetchall()]


def create_product(conn, name: str, notes: str | None = None, *, lot_code_prefix: str | None = None,
                    actor: str | None = None) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_products (name, notes, lot_code_prefix) VALUES (%s, %s, %s) "
            "RETURNING id, name, active, notes, lot_code_prefix",
            (name.strip(), notes, lot_code_prefix.strip() if lot_code_prefix else None),
        )
        row = dict(cur.fetchone())
    audit.log(conn, actor=actor, action="create", entity="yield_product", entity_id=row["id"], after=row)
    conn.commit()
    return row


def update_product(conn, product_id: int, *, name: str | None = None, active: bool | None = None,
                    notes: str | None = None, lot_code_prefix: str | None = None,
                    actor: str | None = None) -> dict:
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
    if lot_code_prefix is not None:
        sets.append("lot_code_prefix = %s")
        vals.append(lot_code_prefix.strip() or None)
    if not sets:
        raise ValueError("nothing to update")
    sets.append("updated_at = now()")
    vals.append(product_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"UPDATE yield_products SET {', '.join(sets)} WHERE id = %s "
            "RETURNING id, name, active, notes, lot_code_prefix",
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


# --- yield product <-> sales SKU links --------------------------------------
# Many-to-many (yield_product_sales_links), not the customer_aliases N:1-alias
# shape — see supabase/migrations/0014_yields.sql for why: a yield product can
# feed several sold SKUs, and a blend SKU pulls from several yield products.


def list_links(conn, *, yield_product_id: int | None = None) -> list[dict]:
    where = "WHERE l.yield_product_id = %s" if yield_product_id is not None else ""
    vals = (yield_product_id,) if yield_product_id is not None else ()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT l.id, l.yield_product_id, l.sales_product_name, p.name AS product_name
            FROM yield_product_sales_links l
            JOIN yield_products p ON p.id = l.yield_product_id
            {where}
            ORDER BY p.name, l.sales_product_name
            """,
            vals,
        )
        return [dict(r) for r in cur.fetchall()]


def create_link(conn, yield_product_id: int, sales_product_name: str, *, actor: str | None = None) -> dict:
    """Idempotent — linking the same pair twice just returns the existing row,
    rather than erroring on the UNIQUE(yield_product_id, sales_product_name)."""
    name = sales_product_name.strip()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_product_sales_links (yield_product_id, sales_product_name) "
            "VALUES (%s, %s) ON CONFLICT (yield_product_id, sales_product_name) DO NOTHING "
            "RETURNING id, yield_product_id, sales_product_name",
            (yield_product_id, name),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT id, yield_product_id, sales_product_name FROM yield_product_sales_links "
                "WHERE yield_product_id = %s AND sales_product_name = %s",
                (yield_product_id, name),
            )
            row = cur.fetchone()
        row = dict(row)
    audit.log(conn, actor=actor, action="create", entity="yield_link", entity_id=row["id"], after=row)
    conn.commit()
    return row


def delete_link(conn, link_id: int, *, actor: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yield_product_sales_links WHERE id = %s", (link_id,))
        gone = cur.rowcount
    if gone:
        audit.log(conn, actor=actor, action="delete", entity="yield_link", entity_id=link_id)
    conn.commit()


def sales_product_names(conn) -> list[str]:
    """Existing PO/QBO sales-side product names, for the SKU-link picker —
    reuses services/settings.py's list_products() union query (the same names
    the Settings -> Visibility -> Products hide/show list offers) rather than
    duplicating that SQL. Hidden names are excluded — nothing should link a
    yield product to a sales name that's already hidden from every report."""
    from . import settings as settings_svc

    return [r["name"] for r in settings_svc.list_products(conn) if not r["hidden"]]


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
                  lot_code: str | None = None,
                  harvested_by: str, notes: str | None = None, submitted_by: str) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO yield_entries
                (yield_product_id, harvest_date, weight, unit, tray_count,
                 discarded_tray_count, lot_code, harvested_by, notes, submitted_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (yield_product_id, harvest_date, weight, unit, tray_count, discarded_tray_count,
             lot_code, harvested_by, notes, submitted_by),
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
    "weight", "unit", "tray_count", "discarded_tray_count",
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


# --- trends ----------------------------------------------------------------


def trends(conn, *, date_from: _date | None, date_to: _date | None,
           yield_product_ids: list[int] | None, grain: str = "month") -> PageResponse:
    """Weight + tray rollups by period, for the office Trends page. `grain` must
    already be validated against GRAINS by the caller — it's interpolated into
    date_trunc() as a bind parameter, not a literal, so an invalid value just
    errors rather than injects, but the router should reject it before this
    query ever runs."""
    where = ["NOT e.voided"]
    params: dict[str, object] = {"grain": grain}
    if date_from is not None:
        where.append("e.harvest_date >= %(date_from)s")
        params["date_from"] = date_from
    if date_to is not None:
        where.append("e.harvest_date <= %(date_to)s")
        params["date_to"] = date_to
    if yield_product_ids:
        where.append("e.yield_product_id = ANY(%(product_ids)s)")
        params["product_ids"] = yield_product_ids
    where_sql = " AND ".join(where)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT date_trunc(%(grain)s, e.harvest_date)::date AS period,
                   p.name AS product_name,
                   sum(e.weight * CASE e.unit
                       WHEN 'oz' THEN 1 WHEN 'lb' THEN 16 WHEN 'g' THEN 0.0352739619
                       END) AS weight_oz,
                   sum(e.tray_count) AS trays,
                   sum(e.discarded_tray_count) AS discarded_trays,
                   count(*) AS n_entries
            FROM yield_entries e
            JOIN yield_products p ON p.id = e.yield_product_id
            WHERE {where_sql}
            GROUP BY 1, 2
            ORDER BY 1
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]

    periods = sorted({r["period"].isoformat() for r in rows})
    by_product: dict[str, dict[str, float]] = {}
    total_by_period = dict.fromkeys(periods, 0.0)
    trays_by_period = dict.fromkeys(periods, 0.0)
    discarded_by_period = dict.fromkeys(periods, 0.0)

    for r in rows:
        period = r["period"].isoformat()
        weight = float(r["weight_oz"] or 0)
        by_product.setdefault(r["product_name"], dict.fromkeys(periods, 0.0))[period] += weight
        total_by_period[period] += weight
        trays_by_period[period] += float(r["trays"] or 0)
        discarded_by_period[period] += float(r["discarded_trays"] or 0)

    # One line per selected product when the caller filtered to specific ones
    # (otherwise a busy multi-crop chart is more confusing than useful) — else
    # a single "All products" total.
    if yield_product_ids:
        weight_series = [
            ChartSeries(name=name, data=[round(vals[p], 1) for p in periods])
            for name, vals in sorted(by_product.items())
        ]
    else:
        weight_series = [
            ChartSeries(name="All products", data=[round(total_by_period[p], 1) for p in periods])
        ]

    charts = [
        Chart(
            id="yields-weight", title="Harvest weight (oz)", kind="line",
            x=periods, series=weight_series, y_format="int",
        ),
        Chart(
            id="yields-trays", title="Trays harvested vs. discarded", kind="bar",
            x=periods, y_format="int",
            series=[
                ChartSeries(name="Harvested", data=[trays_by_period[p] for p in periods]),
                ChartSeries(name="Discarded", data=[discarded_by_period[p] for p in periods]),
            ],
        ),
    ]

    total_weight = sum(total_by_period.values())
    total_trays = sum(trays_by_period.values())
    total_discarded = sum(discarded_by_period.values())
    tray_universe = total_trays + total_discarded
    discard_rate = (total_discarded / tray_universe * 100) if tray_universe > 0 else 0.0

    kpis = [
        Kpi(label="Harvest weight", value=round(total_weight, 1), format="int", north_star=True,
            help="Sum across the selected range and products, normalized to ounces."),
        Kpi(label="Trays harvested", value=int(total_trays), format="int"),
        Kpi(label="Trays discarded", value=int(total_discarded), format="int"),
        Kpi(label="Discard rate", value=round(discard_rate, 1), format="percent"),
    ]

    return PageResponse(
        scope=Scope(
            count=len(rows), noun="entries",
            start=date_from.isoformat() if date_from else None,
            end=date_to.isoformat() if date_to else None,
        ),
        kpis=kpis,
        charts=charts,
    )


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


# --- employees ---------------------------------------------------------------
# A roster so the kiosk's "harvested by" field is a tap-to-pick Select. Free
# TEXT on yield_entries.harvested_by is unchanged (no FK) — this is a curated
# suggestion list, not a referential-integrity change, so renaming/retiring/
# deleting an employee never touches existing entry history.


def list_employees(conn, *, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else "WHERE active"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT id, name, active FROM yield_employees {where} ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


def create_employee(conn, name: str, *, actor: str | None = None) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_employees (name) VALUES (%s) RETURNING id, name, active",
            (name.strip(),),
        )
        row = dict(cur.fetchone())
    audit.log(conn, actor=actor, action="create", entity="yield_employee", entity_id=row["id"], after=row)
    conn.commit()
    return row


def update_employee(conn, employee_id: int, *, name: str | None = None, active: bool | None = None,
                     actor: str | None = None) -> dict:
    sets: list[str] = []
    vals: list[object] = []
    if name is not None:
        sets.append("name = %s")
        vals.append(name.strip())
    if active is not None:
        sets.append("active = %s")
        vals.append(active)
    if not sets:
        raise ValueError("nothing to update")
    sets.append("updated_at = now()")
    vals.append(employee_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"UPDATE yield_employees SET {', '.join(sets)} WHERE id = %s RETURNING id, name, active",
            vals,
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound(f"yield employee {employee_id} not found")
        row = dict(row)
    audit.log(conn, actor=actor, action="edit", entity="yield_employee", entity_id=employee_id, after=row)
    conn.commit()
    return row


def delete_employee(conn, employee_id: int, *, actor: str | None = None) -> None:
    """Always safe — no FK references it, so unlike delete_product this never
    raises InUse; existing entries keep whatever harvested_by text they have."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yield_employees WHERE id = %s", (employee_id,))
        gone = cur.rowcount
    if not gone:
        raise NotFound(f"yield employee {employee_id} not found")
    audit.log(conn, actor=actor, action="delete", entity="yield_employee", entity_id=employee_id)
    conn.commit()
