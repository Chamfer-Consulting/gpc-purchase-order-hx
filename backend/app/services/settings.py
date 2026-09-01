"""Settings — product visibility (hidden_products) and saved views
(dashboard_saved_views). Direct SQL on a reused psycopg2 conn; ported from
dashboard/data.py's set_product_hidden / load_saved_views / save_view /
delete_view and dashboard/views/settings.py."""

from __future__ import annotations

import json

import psycopg2.extras


def list_products(conn) -> list[dict]:
    """Every product name seen on an active PO (plus any still-hidden name that no
    longer appears), each with its current hidden flag and a usage count."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH seen AS (
                SELECT li.product_name, count(*) AS n_lines
                FROM line_items li
                JOIN purchase_orders po ON po.id = li.po_id
                WHERE po.status = 'active'
                  AND li.product_name IS NOT NULL AND li.product_name <> ''
                GROUP BY li.product_name
            )
            SELECT COALESCE(s.product_name, h.product_name) AS name,
                   COALESCE(s.n_lines, 0) AS n_lines,
                   (h.product_name IS NOT NULL) AS hidden
            FROM seen s
            FULL OUTER JOIN hidden_products h ON h.product_name = s.product_name
            ORDER BY 1
            """
        )
        return [dict(r) for r in cur.fetchall()]


def set_product_hidden(conn, product_name: str, hidden: bool) -> None:
    _set_hidden(conn, "hidden_products", "product_name", product_name, hidden)


def list_customers(conn) -> list[dict]:
    """Every customer_name seen on an invoice (plus any still-hidden name that no
    longer appears), each with its current hidden flag and an invoice count.
    Keyed on the invoice customer_name — the value services/context.py groups by."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH seen AS (
                SELECT customer_name, count(*) AS n_lines
                FROM qbo_invoices
                WHERE customer_name IS NOT NULL AND customer_name <> ''
                GROUP BY customer_name
            )
            SELECT COALESCE(s.customer_name, h.customer_name) AS name,
                   COALESCE(s.n_lines, 0) AS n_lines,
                   (h.customer_name IS NOT NULL) AS hidden
            FROM seen s
            FULL OUTER JOIN hidden_customers h ON h.customer_name = s.customer_name
            ORDER BY 1
            """
        )
        return [dict(r) for r in cur.fetchall()]


def set_customer_hidden(conn, customer_name: str, hidden: bool) -> None:
    _set_hidden(conn, "hidden_customers", "customer_name", customer_name, hidden)


def _set_hidden(conn, table: str, col: str, value: str, hidden: bool) -> None:
    with conn.cursor() as cur:
        if hidden:
            cur.execute(
                f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING",
                (value,),
            )
        else:
            cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (value,))
    conn.commit()


# --- team / access control (app_users) -----------------------------------

_TEAM_ROLES = ("viewer", "editor", "admin")


class TeamError(ValueError):
    """Bad Team change — 422 at the router (unknown role, last admin, self-lockout)."""


def list_team(conn) -> list[dict]:
    """Everyone with a login OR a granted role. `role` is NULL for a signed-in
    user who was never assigned one (they run as the default, viewer, IF their
    email is allowed). `allowed` is the identity gate — false = signed up but
    can't get past the API."""
    from ..auth import _DEFAULT_ROLE, email_allowed

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT lower(COALESCE(u.email, a.email))  AS email,
                   a.role, a.note,
                   u.created_at       AS signed_up_at,
                   u.last_sign_in_at  AS last_sign_in_at,
                   (u.id IS NOT NULL) AS has_account
            FROM auth.users u
            FULL OUTER JOIN app_users a ON lower(a.email) = lower(u.email)
            """
        )
        rows = cur.fetchall()

    def _iso(v):
        return v.isoformat() if v is not None else None

    out = []
    for r in rows:
        email = r["email"]
        allowed = r["role"] is not None or email_allowed(email)
        out.append({
            "email": email,
            "role": r["role"],
            "effective_role": r["role"] or (_DEFAULT_ROLE if allowed else None),
            "allowed": allowed,
            "has_role": r["role"] is not None,
            "has_account": r["has_account"],
            "note": r["note"],
            "signed_up_at": _iso(r["signed_up_at"]),
            "last_sign_in_at": _iso(r["last_sign_in_at"]),
        })
    _RANK = {"admin": 0, "editor": 1, "viewer": 2, None: 3}
    out.sort(key=lambda x: (_RANK.get(x["effective_role"], 3), not x["allowed"], x["email"]))
    return out


def _admin_emails(cur) -> set[str]:
    cur.execute("SELECT lower(email) FROM app_users WHERE role = 'admin'")
    return {r[0] for r in cur.fetchall()}


def set_team_member(conn, actor: str | None, email: str, role: str, note: str | None) -> None:
    email = (email or "").strip().lower()
    role = (role or "").strip().lower()
    if "@" not in email:
        raise TeamError("a valid email is required")
    if role not in _TEAM_ROLES:
        raise TeamError(f"role must be one of {', '.join(_TEAM_ROLES)}")
    with conn.cursor() as cur:
        admins = _admin_emails(cur)
        if role != "admin" and admins == {email}:
            raise TeamError("can't demote the last admin")
        cur.execute(
            """
            INSERT INTO app_users (email, role, note) VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET role = EXCLUDED.role, note = EXCLUDED.note, updated_at = now()
            """,
            (email, role, note or None),
        )
    from . import audit
    audit.log(conn, actor=actor, action="team_set", entity="app_user", entity_id=email,
              after={"role": role, "note": note})
    conn.commit()


def remove_team_member(conn, actor: str | None, email: str) -> None:
    email = (email or "").strip().lower()
    with conn.cursor() as cur:
        admins = _admin_emails(cur)
        if email in admins and len(admins) == 1:
            raise TeamError("can't remove the last admin")
        cur.execute("DELETE FROM app_users WHERE lower(email) = %s", (email,))
        removed = cur.rowcount
    if removed:
        from . import audit
        audit.log(conn, actor=actor, action="team_remove", entity="app_user", entity_id=email)
    conn.commit()


def list_views(conn, kind: str, owner: str) -> list[dict]:
    """A user's own saved views for `kind`, plus any legacy shared ones
    (owner = '') migrated from before views were per-user (0007)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, config FROM dashboard_saved_views "
            "WHERE kind = %s AND owner IN (%s, '') ORDER BY created_at",
            (kind, owner),
        )
        return [{"name": n, "config": c} for n, c in cur.fetchall()]


def save_view(conn, kind: str, name: str, config: dict, owner: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dashboard_saved_views (name, kind, config, owner) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (owner, kind, name) DO UPDATE SET config = EXCLUDED.config, created_at = now()",
            (name, kind, json.dumps(config), owner),
        )
    conn.commit()


def delete_view(conn, kind: str, name: str, owner: str) -> None:
    """Only your own view — legacy shared views (owner = '') are read-only."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dashboard_saved_views WHERE kind = %s AND name = %s AND owner = %s",
            (kind, name, owner),
        )
    conn.commit()
