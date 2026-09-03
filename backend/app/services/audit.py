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


# Only a de-bounce, not a real cap: the SPA can fire the same event two or three
# times in a burst (SIGNED_IN + the /auth/callback safety net + a quick reload),
# so collapse repeats of the SAME event for the SAME email inside a short window.
# A genuine sign-out→sign-in still lands two rows — the prior 'login' is older
# than this.
_AUTH_EVENTS = {"login": "2 minutes", "logout": "2 minutes", "login_denied": "1 hour"}


def record_auth_event(conn, *, email: str, event: str,
                      session_id: str | None = None,
                      user_agent: str | None = None,
                      reason: str | None = None) -> bool:
    """Write a 'login' / 'logout' / 'login_denied' row into audit_log, de-bounced
    per (email, event) over a short window (see _AUTH_EVENTS). Returns True if a
    row was actually inserted. Does NOT commit — the caller owns the transaction."""
    if event not in _AUTH_EVENTS:
        raise ValueError(f"bad auth event {event!r}")
    after = {
        k: v
        for k, v in (
            ("session_id", session_id),
            ("user_agent", (user_agent or "").strip()[:300] or None),
            ("reason", (reason or "").strip() or None),
        )
        if v
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (actor, action, entity, entity_id, after)
            SELECT %(email)s, %(event)s, 'app_user', %(email)s, %(after)s::jsonb
            WHERE NOT EXISTS (
                SELECT 1 FROM audit_log
                WHERE action = %(event)s
                  AND entity = 'app_user'
                  AND entity_id = %(email)s
                  AND at > now() - %(window)s::interval
            )
            """,
            {
                "email": email,
                "event": event,
                "after": json.dumps(after) if after else None,
                "window": _AUTH_EVENTS[event],
            },
        )
        return cur.rowcount > 0


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


# --- cross-system activity feed (the /audit admin page) ------------------

# The "why" is not a column — it rides inside the before/after slice under one of
# these keys (newest wins: an `after` value beats a `before` one).
_REASON_KEYS = ("reason", "status_reason", "void_reason", "math_ack_reason", "note")


def derive_reason(before: dict | None, after: dict | None) -> str | None:
    for src in (after, before):
        if not isinstance(src, dict):
            continue
        for k in _REASON_KEYS:
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


# One shape across every source: admin mutations (audit_log) and extraction-review
# decisions (extraction_reviews). Connection events, scheduled pipeline runs
# (notify_run.py) and sign-in/out events are all written straight into audit_log;
# the CASE re-buckets them so 'admin' stays "a person changed data by hand".
_FEED_CTE = """
WITH feed AS (
    SELECT CASE WHEN action IN ('login', 'logout', 'login_denied') THEN 'auth'
                WHEN entity = 'pipeline'                            THEN 'pipeline'
                ELSE 'admin' END AS source,
           'a' || id::text AS id,
           at,
           actor,
           action,
           entity,
           entity_id,
           before,
           after
    FROM audit_log
    UNION ALL
    SELECT 'review'::text        AS source,
           'r' || id::text       AS id,
           updated_at            AS at,
           reviewer              AS actor,
           verdict               AS action,
           'extraction_review'::text AS entity,
           target_key            AS entity_id,
           NULL::jsonb           AS before,
           jsonb_strip_nulls(jsonb_build_object(
               'verdict',     verdict,
               'target_kind', target_kind,
               'revision_of', revision_of,
               'standalone',  standalone,
               'corrected',   corrected,
               'note',        note
           ))                    AS after
    FROM extraction_reviews
)
"""

_TIMELINE_SQL = _FEED_CTE + """
SELECT * FROM feed t
WHERE (%(actor)s  IS NULL OR t.actor  ILIKE %(actor)s)
  AND (%(source)s IS NULL OR t.source =     %(source)s)
  AND (%(action)s IS NULL OR t.action =     %(action)s)
  AND (%(entity)s IS NULL OR t.entity =     %(entity)s)
  AND (%(since)s  IS NULL OR t.at >=        %(since)s)
  AND (%(until)s  IS NULL OR t.at <         %(until)s)
  AND (%(q)s IS NULL
       OR t.actor ILIKE %(q)s OR t.entity_id ILIKE %(q)s OR t.action ILIKE %(q)s
       OR t.before::text ILIKE %(q)s OR t.after::text ILIKE %(q)s)
ORDER BY t.at DESC NULLS LAST, t.id DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

_FACETS_SQL = _FEED_CTE + """
SELECT
  (SELECT array_agg(DISTINCT actor  ORDER BY actor)  FROM feed WHERE actor  IS NOT NULL AND actor  <> '') AS actors,
  (SELECT array_agg(DISTINCT action ORDER BY action) FROM feed WHERE action IS NOT NULL AND action <> '') AS actions,
  (SELECT array_agg(DISTINCT entity ORDER BY entity) FROM feed WHERE entity IS NOT NULL AND entity <> '') AS entities
"""


def timeline(conn, *, actor=None, source=None, action=None, entity=None,
             q=None, since=None, until=None, limit: int = 50,
             offset: int = 0) -> dict:
    """Filtered cross-system activity feed for the admin audit page. Returns
    {"rows": [...newest first...], "has_more": bool}. `reason` is derived from the
    before/after slice; `since`/`until` are compared as-is (pass a date or a
    timestamp; `until` should already be the exclusive upper bound)."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    params = {
        "actor": f"%{actor}%" if actor else None,
        "source": source or None,
        "action": action or None,
        "entity": entity or None,
        "q": f"%{q}%" if q else None,
        "since": since or None,
        "until": until or None,
        "limit": limit + 1,  # one extra row => has_more without a COUNT
        "offset": offset,
    }
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_TIMELINE_SQL, params)
        rows = cur.fetchall()
    has_more = len(rows) > limit
    out = []
    for r in rows[:limit]:
        d = dict(r)
        d["at"] = d["at"].isoformat() if d["at"] else None
        d["reason"] = derive_reason(d.get("before"), d.get("after"))
        out.append(d)
    return {"rows": out, "has_more": has_more}


def facets(conn) -> dict:
    """Distinct actors / actions / entities across the feed, for the filter
    dropdowns. `sources` is the fixed set."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_FACETS_SQL)
        row = cur.fetchone() or {}
    return {
        "actors": list(row.get("actors") or []),
        "actions": list(row.get("actions") or []),
        "entities": list(row.get("entities") or []),
        "sources": ["admin", "auth", "pipeline", "review"],
    }
