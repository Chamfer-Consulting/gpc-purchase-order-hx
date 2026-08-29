"""Append-only change log for the admin-CRUD surface. Every create / edit / status
change / delete / link writes one row: who, what action, which entity, and the
before/after slice as JSON. Written on the same psycopg2 connection as the
mutation (call before the mutation's commit) so an audit row and its change land
together."""

import json
from datetime import date, datetime
from decimal import Decimal

import psycopg2.extras


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, memoryview)):
        return None
    return v


def _clean(d: dict | None) -> dict | None:
    if d is None:
        return None
    return {k: _plain(v) for k, v in d.items()}


def log(conn, *, actor: str | None, action: str, entity: str,
        entity_id: str | int | None, before: dict | None = None,
        after: dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (actor, action, entity, entity_id, before, after)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                actor, action, entity,
                str(entity_id) if entity_id is not None else None,
                json.dumps(_clean(before)) if before is not None else None,
                json.dumps(_clean(after)) if after is not None else None,
            ),
        )


def history(conn, entity: str, entity_id: str | int, limit: int = 100) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, actor, action, entity, entity_id, before, after, at
            FROM audit_log
            WHERE entity = %s AND entity_id = %s
            ORDER BY at DESC, id DESC
            LIMIT %s
            """,
            (entity, str(entity_id), limit),
        )
        return [
            {**dict(r), "at": r["at"].isoformat() if r["at"] else None}
            for r in cur.fetchall()
        ]
