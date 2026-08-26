"""
Shared palette, chart/format helpers, and Postgres data access for the dashboard.

Extracted from the former monolithic app.py (Phase 1 of the navigation/UI overhaul —
see /Users/jcaternolo/.claude/plans/golden-soaring-robin.md) so both app.py (the
composition root) and every dashboard/views/*.py page can import the same helpers
and cached loaders without duplicating them. Logic here is unchanged from the
original app.py — this is a mechanical extraction, not a rewrite.
"""

import os
from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st

from math_check import validate_math

# ── Palette (validated colorblind-safe set — see dataviz skill / schema.sql sibling) ──
# Both Light and Dark are selected palettes from the same reference instance, not an
# automatic flip — same categorical order, dark-surface steps, per the skill's palette.md.
LIGHT = {
    "categorical": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "sequential_blue": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
    "ink_primary": "#0b0b0b",
    "ink_muted": "#898781",
    "grid": "#e1e0d9",
    "surface": "#fcfcfb",
    "page_plane": "#f9f9f7",
}
DARK = {
    "categorical": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    "sequential_blue": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
    "ink_primary": "#ffffff",
    "ink_muted": "#898781",
    "grid": "#2c2c2a",
    "surface": "#1a1a19",
    "page_plane": "#0d0d0d",
}

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def style(fig: go.Figure, palette: dict, height: int | None = None) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=palette["surface"],
        plot_bgcolor=palette["surface"],
        font=dict(color=palette["ink_primary"], family=FONT_FAMILY),
        xaxis=dict(gridcolor=palette["grid"], linecolor=palette["ink_muted"], zeroline=False),
        yaxis=dict(gridcolor=palette["grid"], linecolor=palette["ink_muted"], zeroline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor=palette["surface"], font_family=FONT_FAMILY),
    )
    if height is not None:
        fig.update_layout(height=height)
    return fig


def color_map_for(categories: list[str], palette: dict) -> dict:
    """Fixed hue per category (alphabetical order) so a category keeps its color
    across every chart and across filter changes — never repainted."""
    ordered = sorted(categories)
    cat_colors = palette["categorical"]
    colors = {}
    for i, cat in enumerate(ordered):
        colors[cat] = cat_colors[i] if i < len(cat_colors) else palette["ink_muted"]
    return colors


def fmt_delta(value, prefix: str = "", decimals: int = 0):
    """Formats a KPI delta for st.metric, or returns None (no delta shown) if unavailable."""
    if value is None or pd.isna(value):
        return None
    return f"{prefix}{value:+,.{decimals}f}"


def strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Excel can't hold timezone-aware datetimes — Postgres TIMESTAMPTZ columns
    (e.g. extracted_at) come back tz-aware from psycopg2; drop the tz for export."""
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_localize(None)
    return df


def month_over_month_movers(df: pd.DataFrame, date_col: str, group_col: str, value_col: str, top_n: int = 8):
    """Compares the two most recent distinct months present in df, grouped by group_col.
    Returns (movers_df, current_month, previous_month), or None if fewer than 2 months exist."""
    d = df.dropna(subset=[date_col, group_col]).copy()
    if d.empty:
        return None
    d["month"] = d[date_col].dt.to_period("M")
    months = sorted(d["month"].unique())
    if len(months) < 2:
        return None
    curr_m, prev_m = months[-1], months[-2]
    curr = d[d["month"] == curr_m].groupby(group_col)[value_col].sum()
    prev = d[d["month"] == prev_m].groupby(group_col)[value_col].sum()
    merged = pd.DataFrame({"prev": prev, "curr": curr}).fillna(0.0)
    merged["delta"] = merged["curr"] - merged["prev"]
    merged = merged.reindex(merged["delta"].abs().sort_values(ascending=False).index).head(top_n)
    merged = merged.reset_index().rename(columns={"index": group_col})
    merged["Change"] = merged["delta"].apply(lambda v: f"▲ +${v:,.0f}" if v >= 0 else f"▼ -${abs(v):,.0f}")
    return merged, curr_m, prev_m


def compare_periods_by_group(
    df: pd.DataFrame, date_col: str, group_col: str, value_col: str,
    range_a: tuple, range_b: tuple, top_n: int = 10,
) -> pd.DataFrame | None:
    """Like month_over_month_movers, but for two arbitrary custom date ranges instead
    of the two most recent calendar months — range_a/range_b are (start_ts, end_ts)
    tuples. Returns a DataFrame with columns [group_col, "A", "B", "delta"], the
    top_n rows by |delta|, or None if there's no data in either range."""
    a_start, a_end = range_a
    b_start, b_end = range_b
    d = df.dropna(subset=[date_col, group_col])
    a = d[(d[date_col] >= a_start) & (d[date_col] <= a_end)].groupby(group_col)[value_col].sum()
    b = d[(d[date_col] >= b_start) & (d[date_col] <= b_end)].groupby(group_col)[value_col].sum()
    if a.empty and b.empty:
        return None
    merged = pd.DataFrame({"A": a, "B": b}).fillna(0.0)
    merged["delta"] = merged["B"] - merged["A"]
    merged = merged.reindex(merged["delta"].abs().sort_values(ascending=False).index).head(top_n)
    return merged.reset_index().rename(columns={"index": group_col})


def top_entity_per_period(detail_df: pd.DataFrame, period_col: str, entity_col: str, value_col: str, agg: str = "sum") -> pd.Series:
    """Returns a Series indexed by period value -> "entity (value)" string for whichever
    entity_col value is largest in that period — used to enrich a chart's hover tooltip
    (merge the result onto the chart's already-grouped dataframe by period_col) so
    hovering a bar shows more than just the raw aggregate number. Empty Series if
    detail_df has nothing to summarize."""
    if detail_df.empty:
        return pd.Series(dtype=object)
    grouped = detail_df.dropna(subset=[period_col, entity_col]).groupby([period_col, entity_col])[value_col].agg(agg).reset_index()
    if grouped.empty:
        return pd.Series(dtype=object)
    idx = grouped.groupby(period_col)[value_col].idxmax()
    top = grouped.loc[idx].set_index(period_col)
    return top.apply(lambda r: f"{r[entity_col]} ({r[value_col]:,.0f})", axis=1)


def yoy_annual_chart(df: pd.DataFrame, date_col: str, agg_col: str, agg_fn: str, y_label: str, palette: dict, current_year: str):
    """Line chart with one line per calendar year (month-of-year on the x-axis),
    current_year emphasized (bold, full opacity) against past years (thin, dotted,
    muted) for an at-a-glance annual comparison. Returns None if there's no dated data."""
    import plotly.express as px

    src = df.dropna(subset=[date_col]).copy()
    if src.empty:
        return None
    src["year"] = src[date_col].dt.year.astype(str)
    src["moy"] = src[date_col].dt.month
    if agg_fn == "nunique":
        grouped = src.groupby(["year", "moy"])[agg_col].nunique().reset_index(name="value")
    else:
        grouped = src.groupby(["year", "moy"])[agg_col].sum().reset_index(name="value")
    if grouped.empty:
        return None

    year_colors = color_map_for(grouped["year"].unique().tolist(), palette)
    fig = px.line(
        grouped, x="moy", y="value", color="year", markers=True,
        color_discrete_map=year_colors, labels={"moy": "", "value": y_label, "year": "Year"},
    )
    fig.update_xaxes(
        tickmode="array", tickvals=list(range(1, 13)),
        ticktext=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    )
    for trace in fig.data:
        if trace.name == current_year:
            trace.update(line=dict(width=4), opacity=1.0, marker=dict(size=8))
        else:
            trace.update(line=dict(width=1.5, dash="dot"), opacity=0.55, marker=dict(size=5))
    return fig


def get_database_url() -> str:
    url = st.secrets.get("database_url") or os.environ.get("DATABASE_URL")
    if not url:
        st.error("No database configured. Set `database_url` in .streamlit/secrets.toml.")
        st.stop()
    return url


def save_po_edit(po_id: int, header: dict, items: list[dict]) -> None:
    """Writes a manual edit straight to Postgres and marks the PO as edited so
    sync_dashboard.py never overwrites it again (see its ON CONFLICT ... WHERE clause)."""
    data = {"subtotal": header["subtotal"], "tax": header["tax"], "total": header["total"], "line_items": items}
    validate_math(data)

    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE purchase_orders SET
                    po_number = %(po_number)s, customer_name = %(customer_name)s,
                    po_date = %(po_date)s, delivery_date = %(delivery_date)s,
                    subtotal = %(subtotal)s, tax = %(tax)s, total = %(total)s, notes = %(notes)s,
                    math_check_failed = %(math_check_failed)s, math_check_detail = %(math_check_detail)s,
                    edited = TRUE, edited_at = now()
                WHERE id = %(po_id)s
                """,
                {**header, "po_id": po_id,
                 "math_check_failed": data["math_check_failed"], "math_check_detail": data["math_check_detail"]},
            )
            cur.execute("DELETE FROM line_items WHERE po_id = %s", (po_id,))
            for item in items:
                cur.execute(
                    """
                    INSERT INTO line_items (
                        po_id, product_raw, product_name, container_size,
                        quantity, unit_price, line_total, is_sample,
                        math_mismatch, revision_status, is_removed
                    ) VALUES (
                        %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
                        %(quantity)s, %(unit_price)s, %(line_total)s, %(is_sample)s,
                        %(math_mismatch)s, 'Edited', FALSE
                    )
                    """,
                    {
                        "po_id": po_id,
                        "product_raw": item.get("product_name"),
                        "product_name": item.get("product_name"),
                        "container_size": item.get("container_size"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("unit_price"),
                        "line_total": item.get("line_total"),
                        "is_sample": bool(item.get("is_sample", False)),
                        "math_mismatch": item.get("math_mismatch"),
                    },
                )
        conn.commit()
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner="Loading PO data...")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conn = psycopg2.connect(get_database_url())
    try:
        # LEFT JOIN the Gmail thread metadata (who sent it / when / attachments /
        # a link) so the Extraction Errors view and anywhere else can trace a
        # "gmail-thread:…" or bare-PDF-filename row back to the actual email.
        # NULL for local-PDF rows, which is fine — those already carry a real
        # filename in source_file. The table/column are created by the extraction
        # pipeline, which may not have run against this DB yet — fall back to the
        # plain read (with empty gmail_* columns) until it has.
        _GMAIL_META = [
            "gmail_subject", "gmail_from", "gmail_first_message_at",
            "gmail_last_message_at", "gmail_message_count",
            "gmail_attachment_names", "gmail_url",
        ]
        try:
            po_df = pd.read_sql_query(
                """
                SELECT po.*,
                       m.subject          AS gmail_subject,
                       m.from_addrs       AS gmail_from,
                       m.first_message_at AS gmail_first_message_at,
                       m.last_message_at  AS gmail_last_message_at,
                       m.message_count    AS gmail_message_count,
                       m.attachment_names AS gmail_attachment_names,
                       m.url              AS gmail_url
                FROM purchase_orders po
                LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
                """,
                conn,
            )
        except Exception:
            conn.rollback()  # the failed statement aborts the transaction
            po_df = pd.read_sql_query("SELECT * FROM purchase_orders", conn)
            for _c in _GMAIL_META:
                po_df[_c] = pd.NA
        items_df = pd.read_sql_query("SELECT * FROM line_items", conn)
        # One row per CONFIRMED PO<->invoice match — the only pairs anyone has actually
        # verified, not just an algorithm's guess. Powers "requested vs. delivered" views.
        matched_df = pd.read_sql_query(
            """
            SELECT po.id AS po_id, po.po_number, po.source_file, po.customer_name AS po_customer,
                   po.po_date, po.sent_date, po.total AS po_total,
                   inv.id AS invoice_id, inv.doc_number, inv.txn_date, inv.total_amt AS invoice_total
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
    finally:
        conn.close()
    return po_df, items_df, matched_df


@st.cache_data(ttl=300, show_spinner="Loading QuickBooks invoice data...")
def load_invoice_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The full QuickBooks invoice history — every customer, not just the 3 with PO
    documents. This is what makes Overview/Trends/Products/Customers reflect the whole
    business rather than the PO-covered slice of it."""
    conn = psycopg2.connect(get_database_url())
    try:
        inv_df = pd.read_sql_query(
            "SELECT id, doc_number, customer_name, txn_date, ship_date, total_amt, "
            "private_note FROM qbo_invoices",
            conn,
        )
        inv_items_df = pd.read_sql_query(
            "SELECT ii.invoice_id, ii.product_name, ii.container_size, ii.category, "
            "ii.is_sample, ii.quantity, ii.unit_price, ii.line_total, "
            "inv.customer_name, inv.txn_date "
            "FROM qbo_invoice_items ii JOIN qbo_invoices inv ON inv.id = ii.invoice_id",
            conn,
        )
    finally:
        conn.close()
    return inv_df, inv_items_df


def prepare_invoices(inv_df: pd.DataFrame, inv_items_df: pd.DataFrame):
    """Excludes voided invoices — same heuristic as qbo_matcher._VOID_SQL (null/zero
    total, or a private note mentioning void) — and derives effective_date."""
    inv = inv_df[
        inv_df["total_amt"].notna() & (inv_df["total_amt"] != 0)
        & ~inv_df["private_note"].fillna("").str.contains("void", case=False)
    ].copy()
    inv["effective_date"] = pd.to_datetime(inv["txn_date"], errors="coerce")

    items = inv_items_df.merge(inv[["id"]], left_on="invoice_id", right_on="id")
    items["effective_date"] = pd.to_datetime(items["txn_date"], errors="coerce")
    return inv, items


_MATCHED_ITEMS_COLUMNS = [
    "po_id", "invoice_id", "customer_name", "effective_date",
    "product_name", "container_size", "requested_qty", "requested_amount",
    "delivered_qty", "delivered_amount", "po_math_note",
]


@st.cache_data(ttl=300, show_spinner="Loading requested vs. delivered detail...")
def load_matched_line_items() -> pd.DataFrame:
    """Line-item-level requested-vs-delivered detail for every CONFIRMED PO<->invoice
    match — one row per (po_id, invoice_id, product, size). PO and invoice line items
    aren't linked 1:1 (only the PO<->invoice pair is), so this reconstructs the
    comparison: group each side's items by (id, product, size), then outer-merge the two
    groupings so a product requested-but-not-delivered (or vice versa) gets its own row
    with a zero on the missing side, instead of only surfacing the overlap."""
    conn = psycopg2.connect(get_database_url())
    try:
        links = pd.read_sql_query(
            """
            SELECT l.po_id, l.invoice_id, po.customer_name, po.po_date, po.sent_date
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
        if links.empty:
            return pd.DataFrame(columns=_MATCHED_ITEMS_COLUMNS)

        po_ids = links["po_id"].unique().tolist()
        invoice_ids = links["invoice_id"].unique().tolist()
        po_items = pd.read_sql_query(
            "SELECT po_id, product_name, container_size, quantity, line_total, math_mismatch "
            "FROM line_items "
            "WHERE po_id = ANY(%(ids)s) AND is_sample = FALSE AND is_removed = FALSE",
            conn, params={"ids": po_ids},
        )
        inv_items = pd.read_sql_query(
            "SELECT invoice_id, product_name, container_size, quantity, line_total FROM qbo_invoice_items "
            "WHERE invoice_id = ANY(%(ids)s) AND is_sample = FALSE AND category = 'product'",
            conn, params={"ids": invoice_ids},
        )
    finally:
        conn.close()

    links["effective_date"] = pd.to_datetime(links["sent_date"], errors="coerce").fillna(
        pd.to_datetime(links["po_date"], errors="coerce")
    )
    links = links[["po_id", "invoice_id", "customer_name", "effective_date"]]

    po_grouped = po_items.groupby(["po_id", "product_name", "container_size"], as_index=False).agg(
        requested_qty=("quantity", "sum"), requested_amount=("line_total", "sum"),
        po_math_note=("math_mismatch", lambda s: next((x for x in s if x), None)),
    )
    inv_grouped = inv_items.groupby(["invoice_id", "product_name", "container_size"], as_index=False).agg(
        delivered_qty=("quantity", "sum"), delivered_amount=("line_total", "sum"),
    )

    po_side = links.merge(po_grouped, on="po_id", how="left")
    inv_side = links.merge(inv_grouped, on="invoice_id", how="left")

    combined = pd.merge(
        po_side, inv_side,
        on=["po_id", "invoice_id", "customer_name", "effective_date", "product_name", "container_size"],
        how="outer",
    )
    for col in ("requested_qty", "requested_amount", "delivered_qty", "delivered_amount"):
        combined[col] = combined[col].fillna(0.0)
    return combined[_MATCHED_ITEMS_COLUMNS]


@st.cache_data(ttl=300, show_spinner="Loading reference prices...")
def load_reference_prices() -> pd.DataFrame:
    conn = psycopg2.connect(get_database_url())
    try:
        df = pd.read_sql_query(
            "SELECT id, customer_name, product_name, container_size, price, source, edited, edited_at, updated_at "
            "FROM reference_prices ORDER BY customer_name, product_name, container_size",
            conn,
        )
    finally:
        conn.close()
    return df


def save_reference_prices(rows: list[dict]) -> None:
    """Upserts each row straight to Postgres and marks it edited=TRUE so the next
    sync_dashboard.py run never overwrites it — same guard shape as save_po_edit()."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO reference_prices (customer_name, product_name, container_size, price, source, edited, edited_at)
                    VALUES (%(customer_name)s, %(product_name)s, %(container_size)s, %(price)s, 'manual', TRUE, now())
                    ON CONFLICT (customer_name, product_name, container_size) DO UPDATE SET
                        price = EXCLUDED.price, source = 'manual', edited = TRUE, edited_at = now()
                    """,
                    row,
                )
        conn.commit()
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def load_hidden_products() -> set[str]:
    """Product names currently excluded from reporting (see hidden_products in
    schema.sql) — Edit PO and the QuickBooks Invoice Explorer/Item Catalog pages
    intentionally don't consult this; every other page filters by it."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT product_name FROM hidden_products")
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def set_product_hidden(product_name: str, hidden: bool) -> None:
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            if hidden:
                cur.execute(
                    "INSERT INTO hidden_products (product_name) VALUES (%s) "
                    "ON CONFLICT (product_name) DO NOTHING",
                    (product_name,),
                )
            else:
                cur.execute("DELETE FROM hidden_products WHERE product_name = %s", (product_name,))
        conn.commit()
    finally:
        conn.close()


def prepare(po_df: pd.DataFrame, items_df: pd.DataFrame):
    """Dedupe to the latest version of each PO and join line items to it."""
    po = po_df.copy()
    po["po_key"] = po["po_number"].fillna(po["source_file"])
    po["po_date"] = pd.to_datetime(po["po_date"], errors="coerce")
    po["delivery_date"] = pd.to_datetime(po["delivery_date"], errors="coerce")
    po["effective_date"] = pd.to_datetime(po["sent_date"], errors="coerce").fillna(po["po_date"])

    valid_po = po[po["error"].isna()].copy()
    latest_po = (
        valid_po.sort_values(["po_key", "effective_date", "id"])
        .groupby("po_key", as_index=False)
        .tail(1)
        .copy()
    )

    items = items_df.merge(
        po[["id", "po_number", "po_key", "effective_date", "customer_name", "is_revision", "version_label", "error"]],
        left_on="po_id", right_on="id", suffixes=("", "_po"),
    )
    latest_items = items[items["po_id"].isin(latest_po["id"]) & (~items["is_removed"])].copy()

    return valid_po, latest_po, items, latest_items


@dataclass
class AppContext:
    """Per-rerun bundle of theme, filter state, and filtered/unfiltered dataframes
    that every dashboard/views/*.py page renders from. Built once in app.py (the
    composition root) after auth + data loading + sidebar filters, then handed to
    whichever page st.navigation selects — pages never load data themselves except
    where a page already talks to Postgres directly (Match, QuickBooks, and the raw
    queries inside Requested vs Delivered), which Phase 1 intentionally leaves as-is.

    `pages` (set in app.py after both ctx and the st.Page objects are constructed —
    see the circular-reference note there) holds the small subset of StreamlitPage
    objects that dashboard/attention.py's digest needs to deep-link to via
    st.page_link, keyed by the same page-key strings AttentionItem.page uses
    ("data_quality", "match_review", "requested_vs_delivered").
    """

    palette: dict
    theme_type: str

    # Filter state (mirrors the sidebar widgets in app.py)
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None
    selected_customers: list = field(default_factory=list)
    selected_products: list = field(default_factory=list)
    include_samples: bool = False

    # Unfiltered / lightly-derived data
    po_df: pd.DataFrame = None
    valid_po: pd.DataFrame = None
    latest_po: pd.DataFrame = None
    all_items: pd.DataFrame = None
    invoices: pd.DataFrame = None
    inv_items_all: pd.DataFrame = None

    # Filtered (per sidebar filters) — PO-scoped
    f_po: pd.DataFrame = None
    f_items: pd.DataFrame = None

    # Filtered (per sidebar filters) — invoice-scoped (the primary source for Reports)
    f_inv: pd.DataFrame = None
    f_inv_items: pd.DataFrame = None

    # Precomputed aggregates (shared across multiple pages)
    by_product: pd.DataFrame = None
    by_customer: pd.DataFrame = None
    by_product_inv: pd.DataFrame = None
    by_customer_inv: pd.DataFrame = None
    product_colors: dict = field(default_factory=dict)

    # Product names excluded from reporting (see data.load_hidden_products) — already
    # applied to f_items/f_inv_items/by_product*/product_colors/the sidebar product
    # picker by app.py; pages reading all_items/inv_items_all directly (Pricing, Data
    # Quality, the Requested vs Delivered detail query) must filter by this themselves.
    # Edit PO deliberately does not.
    hidden_products: set = field(default_factory=set)

    # StreamlitPage objects for cross-page deep links (see docstring above)
    pages: dict = field(default_factory=dict)
