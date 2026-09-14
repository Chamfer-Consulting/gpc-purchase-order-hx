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

from ..errors import AlreadyVoided, EmptyPatch, Forbidden, ImportFailed, InUse, NameTaken, NotFound
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope
from . import audit

# Every unit an entry can be recorded in, converted to ounces for aggregation
# (oz is the default/most granular unit here — see 0014_yields.sql). Trends
# always report weight in oz; a display-unit toggle is a nice-to-have, not v1.
# The unit strings are our own trusted constants (never user input), so
# building this into a literal SQL CASE is safe — it's the single source
# trends() aggregates with, rather than a second hardcoded copy that could
# drift from this dict.
_OZ_PER_UNIT = {"oz": 1.0, "lb": 16.0, "g": 0.0352739619}
_OZ_PER_UNIT_SQL = "CASE e.unit " + " ".join(
    f"WHEN '{unit}' THEN {factor}" for unit, factor in _OZ_PER_UNIT.items()
) + " END"
GRAINS = ("week", "month", "quarter", "year")

# --- products ----------------------------------------------------------------


def list_products(conn, *, include_inactive: bool = False) -> list[dict]:
    """`has_notes` (not a DB column — computed here) flags a product that has
    either an entry with its own free-text `notes`, or a yield_notes
    observation tied to a lot_code any of its entries used. It's about
    those two "did something worth remembering happen here" note sources,
    not this table's own `notes` (a catalog description field) below."""
    where = "" if include_inactive else "WHERE active"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT DISTINCT yield_product_id FROM yield_entries WHERE notes IS NOT NULL "
            "UNION "
            "SELECT DISTINCT e.yield_product_id FROM yield_entries e "
            "JOIN yield_notes n ON n.lot_code = e.lot_code WHERE n.lot_code IS NOT NULL",
        )
        has_notes_ids = {r["yield_product_id"] for r in cur.fetchall()}
        cur.execute(
            f"SELECT id, name, active, notes, lot_code_prefix FROM yield_products {where} ORDER BY name",
        )
        return [{**dict(r), "has_notes": r["id"] in has_notes_ids} for r in cur.fetchall()]


def create_product(conn, name: str, notes: str | None = None, *, lot_code_prefix: str | None = None,
                    actor: str | None = None) -> dict:
    name = name.strip()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(
                "INSERT INTO yield_products (name, notes, lot_code_prefix) VALUES (%s, %s, %s) "
                "RETURNING id, name, active, notes, lot_code_prefix",
                (name, notes, lot_code_prefix.strip() if lot_code_prefix else None),
            )
        except psycopg2.errors.UniqueViolation as exc:
            # A real trigger path, not just theoretical: YieldsImportPage lets
            # an admin "+ Create" a product for each unmatched CSV name, and
            # two concurrent imports (or a name differing only by casing that
            # the client's own case-insensitive check missed) would otherwise
            # 500 the whole import batch instead of failing just this row.
            raise NameTaken(name) from exc
        row = dict(cur.fetchone())
    audit.log(conn, actor=actor, action="create", entity="yield_product", entity_id=row["id"], after=row)
    conn.commit()
    return row


_PRODUCT_PATCH_FIELDS = {"name", "active", "notes", "lot_code_prefix"}
# Only these two are nullable at the DB level — name and active are both
# NOT NULL, so an explicit `None` for either is dropped rather than applied.
_PRODUCT_NULLABLE_FIELDS = {"notes", "lot_code_prefix"}


def update_product(conn, product_id: int, patch: dict, *, actor: str | None = None) -> dict:
    """`patch` is already `model_dump(exclude_unset=True)`'d by the router.
    notes/lot_code_prefix are nullable and clearable — an explicit `None` for
    either must survive (that's how the admin clears them in
    YieldsAdminPage), unlike the old per-kwarg version which filtered on
    `is not None` and could never actually clear either field."""
    sets: list[str] = []
    vals: list[object] = []
    for k, v in patch.items():
        if k not in _PRODUCT_PATCH_FIELDS:
            continue
        if v is None and k not in _PRODUCT_NULLABLE_FIELDS:
            continue
        if k == "name":
            v = v.strip()
        elif k == "lot_code_prefix" and v is not None:
            v = v.strip() or None
        sets.append(f"{k} = %s")
        vals.append(v)
    if not sets:
        raise EmptyPatch()
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
        try:
            cur.execute(
                "INSERT INTO yield_product_sales_links (yield_product_id, sales_product_name) "
                "VALUES (%s, %s) ON CONFLICT (yield_product_id, sales_product_name) DO NOTHING "
                "RETURNING id, yield_product_id, sales_product_name",
                (yield_product_id, name),
            )
        except psycopg2.errors.ForeignKeyViolation as exc:
            # yield_product_id was deleted (e.g. in another tab) between the
            # admin picker loading and this submit.
            raise NotFound(f"yield product {yield_product_id} not found") from exc
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
    if not gone:
        raise NotFound(f"yield link {link_id} not found")
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


def import_entries(conn, rows: list[dict], *, actor: str) -> dict:
    """Bulk-insert historical harvest entries in one transaction — the CSV
    import flow. Each row carries the same required fields as create_entry
    (yield_product_id/harvest_date/weight/unit/harvested_by; lot_code
    optional); tray counts default 0, notes NULL — historical records don't
    carry those. One audit_log row summarizes the whole batch rather than
    one per row, so a 500-row import doesn't flood the audit trail.

    Skips (doesn't insert) any row that already matches a non-voided entry
    for the same product + date + weight + unit — by lot_code too when the
    row has one, else regardless of the matching existing entry's lot_code
    (matching only lot-code-less existing entries would miss a real
    duplicate whose lot_code was simply left off the re-imported row).
    Weight+unit are always part of the match, not just lot_code+product+date
    — the same lot_code legitimately covers *multiple distinct entries* on
    the same day (e.g. two different people each harvesting into the same
    labeled bin with their own weight); matching on lot_code alone would
    silently collapse those into one and drop real harvest data. This is
    what keeps the "download a template pre-filled with your 5 most recent
    entries" flow from double-entering those rows if the admin imports the
    template without deleting/overwriting them. A duplicate row within the
    same CSV is caught the same way — a row about to be inserted is added to
    the lookup immediately, before the next row is checked.

    Existing entries are pre-fetched once (scoped to the products/dates in
    this batch) and the whole batch is inserted in one multi-row INSERT — a
    per-row SELECT+INSERT round trip doesn't scale to a few-hundred-row
    historical import."""
    if not rows:
        return {"created": 0, "skipped_duplicates": 0}

    product_ids = list({r["yield_product_id"] for r in rows})
    dates = list({r["harvest_date"] for r in rows})

    by_lot: set[tuple[int, object, str, float, str]] = set()
    by_weight: set[tuple[int, object, float, str]] = set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT yield_product_id, harvest_date, lot_code, weight, unit FROM yield_entries "
            "WHERE NOT voided AND yield_product_id = ANY(%s) AND harvest_date = ANY(%s)",
            (product_ids, dates),
        )
        for pid, d, lot, w, u in cur.fetchall():
            rw = round(float(w), 2)
            by_weight.add((pid, d, rw, u))
            if lot:
                by_lot.add((pid, d, lot, rw, u))

    to_insert: list[tuple] = []
    skipped_duplicates = 0
    for r in rows:
        pid, d, w, u = r["yield_product_id"], r["harvest_date"], round(float(r["weight"]), 2), r["unit"]
        lot_code = r.get("lot_code")
        is_dup = (pid, d, lot_code, w, u) in by_lot if lot_code else (pid, d, w, u) in by_weight
        if is_dup:
            skipped_duplicates += 1
            continue
        by_weight.add((pid, d, w, u))
        if lot_code:
            by_lot.add((pid, d, lot_code, w, u))
        to_insert.append((pid, d, r["weight"], r["unit"], lot_code, r["harvested_by"], actor))

    created = 0
    if to_insert:
        with conn.cursor() as cur:
            try:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO yield_entries "
                    "(yield_product_id, harvest_date, weight, unit, lot_code, harvested_by, submitted_by) "
                    "VALUES %s",
                    to_insert,
                )
            except psycopg2.errors.IntegrityError as exc:
                # One multi-row INSERT, one transaction — a single bad row (a
                # product deleted by another admin mid-import, a value that
                # slips past the frontend's own validation) would otherwise
                # 500 the whole batch instead of a clean, actionable error.
                raise ImportFailed() from exc
        created = len(to_insert)
        audit.log(conn, actor=actor, action="import", entity="yield_entry", entity_id=None,
                  after={"count": created, "skipped_duplicates": skipped_duplicates})
    conn.commit()
    return {"created": created, "skipped_duplicates": skipped_duplicates}


def list_entries(conn, *, yield_product_id: int | None = None, date_from: _date | None = None,
                  date_to: _date | None = None, harvested_by: str | None = None,
                  submitted_by: str | None = None, include_voided: bool = False,
                  has_notes: bool = False) -> list[dict]:
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
        # Case-insensitive — matches _assert_can_touch's .lower() ownership
        # check and the codebase's lower()-everywhere email convention.
        where.append("lower(e.submitted_by) = %s")
        vals.append(submitted_by.lower())
    if has_notes:
        # For the Notes page's merged feed — entries carry their own
        # free-text notes (set in the harvest form / edit modal), separate
        # from yield_notes' lot-tied grower observations.
        where.append("e.notes IS NOT NULL")
    sql = ("SELECT e.*, p.name AS product_name, p.lot_code_prefix AS product_lot_code_prefix "
           "FROM yield_entries e JOIN yield_products p ON p.id = e.yield_product_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.harvest_date DESC, e.created_at DESC"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, vals)
        return [_entry_row(dict(r)) for r in cur.fetchall()]


def _assert_can_touch(conn, entry_id: int, *, actor: str | None, actor_role: str) -> dict:
    """A 'field'-rank caller may only touch its own same-day entries; every
    other role (viewer and up) is unrestricted — Yields isn't the sensitive
    domain the 'field' floor exists to protect, PO/financial data is. Voided
    is a terminal state for every role: a voided entry is a corrected/
    retracted record, not something to keep editing or re-void."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM yield_entries WHERE id = %s", (entry_id,))
        row = cur.fetchone()
    if row is None:
        raise NotFound(f"yield entry {entry_id} not found")
    row = dict(row)
    if row["voided"]:
        raise AlreadyVoided()
    if actor_role == "field":
        same_day = row["harvest_date"] == business_now().date()
        own = (row["submitted_by"] or "").lower() == (actor or "").lower()
        if not (same_day and own):
            raise Forbidden(need="viewer", have=actor_role)
    return row


_ENTRY_PATCH_FIELDS = {
    "weight", "unit", "tray_count", "discarded_tray_count",
    "lot_code", "harvested_by", "notes", "harvest_date",
}
# Only these two are nullable at the DB level (yield_entries.lot_code/notes
# have no NOT NULL) — every other patchable field does, so an explicit
# `None` for one of those must be dropped rather than applied, or the
# UPDATE hits a NotNullViolation and 500s.
_ENTRY_NULLABLE_FIELDS = {"lot_code", "notes"}


def update_entry(conn, entry_id: int, patch: dict, *, actor: str | None, actor_role: str) -> dict:
    """`patch` is already `model_dump(exclude_unset=True)`'d by the router, so
    every key present here was explicitly sent by the caller — including an
    explicit `None` for the nullable columns (lot_code, notes), which is how
    the Edit modal clears them. Don't drop those `None`s: a caller that
    wanted a field left alone simply wouldn't include the key at all."""
    row = _assert_can_touch(conn, entry_id, actor=actor, actor_role=actor_role)
    new_harvest_date = patch.get("harvest_date")
    if actor_role == "field" and new_harvest_date is not None and new_harvest_date != row["harvest_date"]:
        # _assert_can_touch only verified the entry's *current* harvest_date is
        # today — without this, a field-role caller could move their own entry
        # to a different day in the same request and escape the same-day
        # self-service window that check exists to enforce.
        raise Forbidden(need="viewer", have=actor_role)
    sets: list[str] = []
    vals: list[object] = []
    for k, v in patch.items():
        if k not in _ENTRY_PATCH_FIELDS:
            continue
        if v is None and k not in _ENTRY_NULLABLE_FIELDS:
            continue
        sets.append(f"{k} = %s")
        vals.append(v)
    if not sets:
        raise EmptyPatch()
    sets.append("updated_at = now()")
    vals.append(entry_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # `AND NOT voided` makes this atomic against a concurrent void: without
        # it, two near-simultaneous requests (an edit racing a void) could both
        # pass _assert_can_touch's earlier read before either write commits.
        cur.execute(
            f"UPDATE yield_entries SET {', '.join(sets)} WHERE id = %s AND NOT voided RETURNING *",
            vals,
        )
        updated = cur.fetchone()
        if updated is None:
            raise AlreadyVoided()
        row = _entry_row(dict(updated))
    audit.log(conn, actor=actor, action="edit", entity="yield_entry", entity_id=entry_id, after=row)
    conn.commit()
    return row


def void_entry(conn, entry_id: int, reason: str | None, *, actor: str | None, actor_role: str) -> dict:
    _assert_can_touch(conn, entry_id, actor=actor, actor_role=actor_role)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # `AND NOT voided` closes the same race as update_entry's — two
        # near-simultaneous void requests could otherwise both pass
        # _assert_can_touch's read and both write (the second silently
        # overwriting the first's void_reason).
        cur.execute(
            "UPDATE yield_entries SET voided = TRUE, void_reason = %s, updated_at = now() "
            "WHERE id = %s AND NOT voided RETURNING *",
            (reason, entry_id),
        )
        updated = cur.fetchone()
        if updated is None:
            raise AlreadyVoided()
        row = _entry_row(dict(updated))
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
                   sum(e.weight * {_OZ_PER_UNIT_SQL}) AS weight_oz,
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


def list_notes(conn, *, lot_code: str | None = None) -> list[dict]:
    where: list[str] = []
    vals: list[object] = []
    if lot_code is not None:
        where.append("lot_code = %s")
        vals.append(lot_code)
    sql = "SELECT * FROM yield_notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY note_date DESC, created_at DESC"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, vals)
        return [_note_row(dict(r)) for r in cur.fetchall()]


def create_note(conn, *, lot_code: str | None, note: str, note_date: _date | None = None,
                 submitted_by: str) -> dict:
    # business_now().date(), not SQL's CURRENT_DATE (the DB session's own
    # timezone, not necessarily America/Chicago) — matches every other
    # "today" in this file. The sole UI caller always sends note_date
    # explicitly today, but a future caller that omits it should still land
    # on the same business day everything else here uses.
    if note_date is None:
        note_date = business_now().date()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO yield_notes (lot_code, note, note_date, submitted_by) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (lot_code.strip() if lot_code else None, note, note_date, submitted_by),
        )
        row = _note_row(dict(cur.fetchone()))
    audit.log(conn, actor=submitted_by, action="create", entity="yield_note", entity_id=row["id"], after=row)
    conn.commit()
    return row


def delete_note(conn, note_id: int, *, actor: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yield_notes WHERE id = %s", (note_id,))
        gone = cur.rowcount
    if not gone:
        raise NotFound(f"yield note {note_id} not found")
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
    name = name.strip()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(
                "INSERT INTO yield_employees (name) VALUES (%s) RETURNING id, name, active",
                (name,),
            )
        except psycopg2.errors.UniqueViolation as exc:
            raise NameTaken(name) from exc
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
        raise EmptyPatch()
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
