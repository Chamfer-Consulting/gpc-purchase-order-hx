"""Settings — product visibility (hidden_products) and saved views
(dashboard_saved_views). Direct SQL on a reused psycopg2 conn; ported from
dashboard/data.py's set_product_hidden / load_saved_views / save_view /
delete_view and dashboard/views/settings.py."""

from __future__ import annotations

import json

import psycopg2.extras

from . import audit


def list_products(conn) -> list[dict]:
    """Every product name the app can hide — the UNION of the two namespaces
    `hidden_products` is matched against: PO-extraction names
    (`line_items.product_name`, used by the Overview attention digest + reference
    prices) and QuickBooks names (`qbo_invoice_items.product_name`, what every
    revenue/analytics page groups on). They diverge for anything outside the
    handful of hard-coded canonical products, so listing only one side let a
    hidden product keep showing on the pages fed by the other."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH seen AS (
                SELECT product_name, sum(n)::bigint AS n_lines
                FROM (
                    SELECT li.product_name, count(*) AS n
                    FROM line_items li
                    JOIN purchase_orders po ON po.id = li.po_id
                    WHERE po.status = 'active'
                      AND li.product_name IS NOT NULL AND li.product_name <> ''
                    GROUP BY li.product_name
                    UNION ALL
                    SELECT ii.product_name, count(*) AS n
                    FROM qbo_invoice_items ii
                    WHERE ii.category = 'product'
                      AND ii.product_name IS NOT NULL
                      AND ii.product_name NOT IN ('', 'UNKNOWN')
                    GROUP BY ii.product_name
                ) u
                GROUP BY product_name
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


def set_product_hidden(conn, product_name: str, hidden: bool, *, actor: str | None = None) -> None:
    _set_hidden(conn, "hidden_products", "product_name", product_name, hidden,
                actor=actor, entity="product")


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


def set_customer_hidden(conn, customer_name: str, hidden: bool, *, actor: str | None = None) -> None:
    _set_hidden(conn, "hidden_customers", "customer_name", customer_name, hidden,
                actor=actor, entity="customer")


# --- customer aliasing --------------------------------------------------------
# customer_aliases(alias_name PK -> canonical_name). The emailer of a PO is a
# buyer at the company; canonical_name is always the company. See customer_alias.py
# (the resolver) and migration 0013.


def list_customer_aliases(conn) -> dict:
    """`groups` = canonicals that fold >=1 other spelling (or were hand-set),
    each with its alias chips; `unaliased` = spellings seen on an active PO or an
    invoice that have no mapping yet; `canonicals` = every canonical name (all QBO
    customers + any manual), the target list when mapping a spelling."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT alias_name, canonical_name, source FROM customer_aliases "
            "ORDER BY canonical_name, alias_name"
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            r"""
            WITH seen AS (
                SELECT DISTINCT customer_name AS name FROM purchase_orders
                WHERE status = 'active'
                  AND customer_name IS NOT NULL AND btrim(customer_name) <> ''
                UNION
                SELECT DISTINCT customer_name FROM qbo_invoices
                WHERE customer_name IS NOT NULL AND btrim(customer_name) <> ''
            )
            -- Case/whitespace-insensitive, matching customer_alias.py's own
            -- _ci_index fallback — an exact-string join here flagged spellings
            -- as "needs mapping" that the resolver already silently folds
            -- (e.g. a different-cased repeat of an existing alias), which is
            -- just noise for whoever works this list in Settings.
            SELECT s.name FROM seen s
            WHERE NOT EXISTS (
                SELECT 1 FROM customer_aliases a
                WHERE lower(regexp_replace(btrim(a.alias_name), '\s+', ' ', 'g'))
                    = lower(regexp_replace(btrim(s.name), '\s+', ' ', 'g'))
            )
            ORDER BY s.name
            """
        )
        unaliased = [r["name"] for r in cur.fetchall()]

    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(
            r["canonical_name"], {"canonical": r["canonical_name"], "aliases": [], "manual": False}
        )
        if r["alias_name"] != r["canonical_name"]:  # the self-row is implied, not a chip
            g["aliases"].append({"name": r["alias_name"], "source": r["source"]})
        if r["source"] == "manual":
            g["manual"] = True

    interesting = sorted(
        (g for g in groups.values() if g["aliases"] or g["manual"]),
        key=lambda g: (-len(g["aliases"]), g["canonical"].lower()),
    )
    return {
        "groups": interesting,
        "unaliased": unaliased,
        "canonicals": sorted(groups.keys(), key=str.lower),
    }


def set_customer_alias(conn, alias_name: str, canonical_name: str, *, actor: str | None = None) -> None:
    """Map one spelling -> a company (source='manual'). Ensures the company has a
    self-row so the resolver always terminates.

    If an existing row is already case/whitespace-equivalent to `alias_name`
    (customer_alias.py's `_ci_index` fallback would already treat them as the
    same spelling), re-point *that* row instead of inserting a new one —
    otherwise a human re-mapping a differently-cased repeat (e.g. typing
    "testa produce" when "Testa Produce" is already mapped) accumulates a
    visually-identical badge in Settings -> Customers that adds no real
    matching coverage the case-insensitive fallback didn't already have."""
    with conn.cursor() as cur:
        cur.execute(
            r"SELECT alias_name FROM customer_aliases "
            r"WHERE lower(regexp_replace(btrim(alias_name), '\s+', ' ', 'g')) "
            r"    = lower(regexp_replace(btrim(%s), '\s+', ' ', 'g')) "
            r"  AND alias_name <> %s "
            r"LIMIT 1",
            (alias_name, alias_name),
        )
        existing = cur.fetchone()
        key = existing[0] if existing else alias_name

        cur.execute(
            "INSERT INTO customer_aliases (alias_name, canonical_name, source) "
            "VALUES (%s, %s, 'manual') ON CONFLICT (alias_name) DO NOTHING",
            (canonical_name, canonical_name),
        )
        cur.execute(
            "INSERT INTO customer_aliases (alias_name, canonical_name, source, updated_at) "
            "VALUES (%s, %s, 'manual', now()) "
            "ON CONFLICT (alias_name) DO UPDATE SET "
            "  canonical_name = EXCLUDED.canonical_name, source = 'manual', updated_at = now()",
            (key, canonical_name),
        )
    audit.log(conn, actor=actor, action="customer_alias", entity="customer",
              entity_id=key, after={"canonical": canonical_name})
    conn.commit()


def delete_customer_alias(conn, alias_name: str, *, actor: str | None = None) -> None:
    """Detach a spelling — it resolves to itself again. A self-row (the canonical
    itself) can't be detached this way."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customer_aliases WHERE alias_name = %s AND alias_name <> canonical_name",
            (alias_name,),
        )
        gone = cur.rowcount
    if gone:
        audit.log(conn, actor=actor, action="customer_alias_remove", entity="customer",
                  entity_id=alias_name, after=None)
    conn.commit()


def rename_customer_canonical(conn, from_name: str, to_name: str, *, actor: str | None = None) -> None:
    """Rename a company — every spelling that pointed at `from_name` (its own
    self-row included) now points at `to_name`. If `to_name` already exists as a
    canonical this is a merge."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_aliases (alias_name, canonical_name, source) "
            "VALUES (%s, %s, 'manual') ON CONFLICT (alias_name) DO NOTHING",
            (to_name, to_name),
        )
        cur.execute(
            "UPDATE customer_aliases SET canonical_name = %s, source = 'manual', updated_at = now() "
            "WHERE canonical_name = %s",
            (to_name, from_name),
        )
        n = cur.rowcount
    audit.log(conn, actor=actor, action="customer_alias_rename", entity="customer",
              entity_id=from_name, after={"to": to_name, "rows": n})
    conn.commit()


def _set_hidden(conn, table: str, col: str, value: str, hidden: bool,
                *, reason: str | None = None,
                actor: str | None = None, entity: str | None = None) -> None:
    with conn.cursor() as cur:
        if hidden:
            if reason is not None:
                cur.execute(
                    f"INSERT INTO {table} ({col}, reason) VALUES (%s, %s) "
                    f"ON CONFLICT ({col}) DO UPDATE SET reason = EXCLUDED.reason",
                    (value, reason),
                )
            else:
                cur.execute(
                    f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING",
                    (value,),
                )
        else:
            cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (value,))
    if entity is not None:
        # "hide" / "unhide" against product | customer | invoice — these drop the
        # row from every report, so they belong on the audit trail.
        audit.log(
            conn, actor=actor,
            action="hide" if hidden else "unhide",
            entity=entity, entity_id=value,
            after={"reason": reason} if (hidden and reason) else None,
        )
    conn.commit()


def list_hidden_invoices(conn) -> list[dict]:
    """Every QBO invoice with a hidden_invoices row, plus enough to identify it.
    Kept small — this is a review/restore list, not the whole invoice history."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT h.qbo_invoice_id, h.reason, h.hidden_at,
                   i.doc_number, i.customer_name, i.txn_date, i.total_amt
            FROM hidden_invoices h
            LEFT JOIN qbo_invoices i ON i.qbo_invoice_id = h.qbo_invoice_id
            ORDER BY h.hidden_at DESC
            """
        )
        return [
            {**dict(r),
             "hidden_at": r["hidden_at"].isoformat() if r["hidden_at"] else None,
             "txn_date": r["txn_date"].isoformat() if r["txn_date"] else None,
             "total_amt": float(r["total_amt"]) if r["total_amt"] is not None else None}
            for r in cur.fetchall()
        ]


def set_invoice_hidden(conn, qbo_invoice_id: str, hidden: bool,
                       reason: str | None = None, *, actor: str | None = None) -> None:
    _set_hidden(conn, "hidden_invoices", "qbo_invoice_id", qbo_invoice_id, hidden,
                reason=reason if hidden else None, actor=actor, entity="invoice")


# --- team / access control (app_users) -----------------------------------

_TEAM_ROLES = ("field", "viewer", "editor", "admin", "external_viewer")


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
                   a.role, a.note, a.external_pages,
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
            "external_pages": list(r["external_pages"] or []),
            "signed_up_at": _iso(r["signed_up_at"]),
            "last_sign_in_at": _iso(r["last_sign_in_at"]),
        })
    _RANK = {"admin": 0, "editor": 1, "viewer": 2, "external_viewer": 3, "field": 4, None: 5}
    out.sort(key=lambda x: (_RANK.get(x["effective_role"], 3), not x["allowed"], x["email"]))
    return out


def _admin_emails(cur) -> set[str]:
    cur.execute("SELECT lower(email) FROM app_users WHERE role = 'admin'")
    return {r[0] for r in cur.fetchall()}


def set_team_member(conn, actor: str | None, email: str, role: str, note: str | None,
                     external_pages: list[str] | None = None) -> None:
    from ..auth import EXTERNAL_VIEWABLE_PAGES

    email = (email or "").strip().lower()
    role = (role or "").strip().lower()
    if "@" not in email:
        raise TeamError("a valid email is required")
    if role not in _TEAM_ROLES:
        raise TeamError(f"role must be one of {', '.join(_TEAM_ROLES)}")
    # Only meaningful for external_viewer — a role switch away from it drops
    # any pages that were granted, so flipping back later starts from a
    # deliberately blank slate rather than resurrecting a stale grant.
    pages = sorted(set(external_pages or [])) if role == "external_viewer" else []
    invalid = [p for p in pages if p not in EXTERNAL_VIEWABLE_PAGES]
    if invalid:
        raise TeamError(f"not a grantable page: {', '.join(invalid)}")
    with conn.cursor() as cur:
        admins = _admin_emails(cur)
        if role != "admin" and admins == {email}:
            raise TeamError("can't demote the last admin")
        cur.execute(
            """
            INSERT INTO app_users (email, role, note, external_pages) VALUES (%s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET role = EXCLUDED.role, note = EXCLUDED.note,
                    external_pages = EXCLUDED.external_pages, updated_at = now()
            """,
            (email, role, note or None, pages),
        )
    audit.log(conn, actor=actor, action="team_set", entity="app_user", entity_id=email,
              after={"role": role, "note": note, "external_pages": pages})
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
    audit.log(conn, actor=owner, action="view_save", entity="saved_view",
              entity_id=f"{kind}/{name}", after={"kind": kind, "name": name})
    conn.commit()


def delete_view(conn, kind: str, name: str, owner: str) -> None:
    """Only your own view — legacy shared views (owner = '') are read-only."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dashboard_saved_views WHERE kind = %s AND name = %s AND owner = %s",
            (kind, name, owner),
        )
        removed = cur.rowcount
    if removed:
        audit.log(conn, actor=owner, action="view_delete", entity="saved_view",
                  entity_id=f"{kind}/{name}", before={"kind": kind, "name": name})
    conn.commit()
