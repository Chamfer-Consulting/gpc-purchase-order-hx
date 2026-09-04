"""
Palette, chart/format helpers, and Postgres data access shared by the FastAPI
backend (`backend/`) and the scheduled pipeline scripts. Formerly
`dashboard/data.py` under the retired Streamlit app; imports cleanly without
Streamlit (see the `try: import streamlit` shim below). See `shared/README.md`.

Some plotly-figure helpers (`style`, `yoy_annual_chart`, `color_map_for`) are
kept for reference / possible reuse; the live charts are built in the React app.
"""

import json
import os
import re
from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import psycopg2.extras

try:
    import streamlit as st
except ModuleNotFoundError:  # headless: the FastAPI backend / CLI scripts import this
    class _NoStreamlit:  # noqa: D401 — minimal shim, only what data.py touches
        secrets: dict = {}

        @staticmethod
        def cache_data(*args, **kwargs):
            """No-op stand-in for @st.cache_data(...). The backend caches at the
            endpoint layer (app.cache) instead."""
            def deco(fn):
                fn.clear = lambda: None
                return fn

            if args and callable(args[0]) and not kwargs:
                return deco(args[0])
            return deco

        @staticmethod
        def error(*args, **kwargs):
            pass

        @staticmethod
        def stop():
            raise RuntimeError("No database configured — set DATABASE_URL.")

    st = _NoStreamlit()

import extraction_reviews
from business_tz import business_now
from math_check import validate_math
from qbo_matcher import customers_match, po_recency

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

# Passed to every st.plotly_chart(): no Plotly wordmark, and a trimmed hover-only
# toolbar (Streamlit already shows it on hover, not permanently).
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "lasso2d", "select2d", "zoomIn2d", "zoomOut2d", "autoScale2d",
        "toggleSpikelines", "hoverClosestCartesian", "hoverCompareCartesian",
    ],
}


def style(fig: go.Figure, palette: dict, height: int | None = None) -> go.Figure:
    """The single house style for every chart. Borderless surface, one light
    horizontal gridline set, no tick marks or axis spines, legend as a top strip,
    unified hover, brand colourway. Orientation-aware: a horizontal bar chart gets
    the value grid on x and the category axis clean on y."""
    horizontal = any(getattr(t, "orientation", None) == "h" for t in fig.data)
    # Respect an explicit fig.update_layout(showlegend=...) from the caller; only
    # auto-decide (hide it for a lone series) when they left it on the default.
    if fig.layout.showlegend is None:
        n_series = len({(getattr(t, "legendgroup", None) or getattr(t, "name", None) or i)
                        for i, t in enumerate(fig.data)})
        show_legend = n_series > 1
    else:
        show_legend = fig.layout.showlegend
    single = not show_legend

    axis_base = dict(
        showline=False, zeroline=False, ticks="", ticklen=0, automargin=True,
        tickfont=dict(size=11, color=palette["ink_muted"]),
        title_font=dict(size=11, color=palette["ink_muted"]),
    )
    clean_axis = {**axis_base, "showgrid": False}
    value_axis = {**axis_base, "showgrid": True, "gridcolor": palette["grid"], "gridwidth": 1}

    fig.update_layout(
        paper_bgcolor=palette["surface"],
        plot_bgcolor=palette["surface"],
        colorway=palette["categorical"],
        font=dict(color=palette["ink_primary"], family=FONT_FAMILY, size=12),
        margin=dict(l=8, r=16, t=36 if not single else 14, b=8),
        hovermode="y unified" if horizontal else "x unified",
        hoverlabel=dict(
            bgcolor=palette["surface"], bordercolor=palette["grid"],
            font=dict(family=FONT_FAMILY, size=12, color=palette["ink_primary"]),
        ),
        bargap=0.28, bargroupgap=0.12,
        showlegend=show_legend,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", title_text="", font=dict(size=11),
        ),
        title=dict(font=dict(size=13, color=palette["ink_muted"]), x=0, xanchor="left"),
    )
    fig.update_xaxes(**(value_axis if horizontal else clean_axis))
    fig.update_yaxes(**(clean_axis if horizontal else value_axis))
    if not horizontal:
        fig.update_xaxes(
            showspikes=True, spikecolor=palette["ink_muted"], spikethickness=1,
            spikedash="dot", spikemode="across", spikesnap="cursor",
        )

    for tr in fig.data:
        if tr.type == "bar":
            tr.update(marker_line_width=0)
        elif tr.type == "scatter" and tr.mode and "lines" in tr.mode:
            tr.update(line=dict(width=2))
            if "markers" in tr.mode:
                tr.update(marker=dict(size=6, line=dict(width=0)))

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


def month_over_month_movers(df: pd.DataFrame, date_col: str, group_col: str, value_col: str,
                            top_n: int = 8, skip_partial_current: bool = True):
    """Compares the two most recent distinct months present in df, grouped by group_col.
    Returns (movers_df, current_month, previous_month, skipped_partial) or None if
    fewer than 2 months exist.

    `skip_partial_current` (default) drops the latest month when it is the current
    calendar month and at least three months of data exist — otherwise a month only
    part-way through is compared against a full prior month and every group looks like
    it's falling. `skipped_partial` reports whether that happened, so the caller's
    caption can say so."""
    d = df.dropna(subset=[date_col, group_col]).copy()
    if d.empty:
        return None
    d["month"] = d[date_col].dt.to_period("M")
    months = sorted(d["month"].unique())
    if len(months) < 2:
        return None
    skipped_partial = (
        skip_partial_current and len(months) >= 3 and months[-1] == pd.Timestamp(business_now()).to_period("M")
    )
    if skipped_partial:
        months = months[:-1]
    curr_m, prev_m = months[-1], months[-2]
    curr = d[d["month"] == curr_m].groupby(group_col)[value_col].sum()
    prev = d[d["month"] == prev_m].groupby(group_col)[value_col].sum()
    merged = pd.DataFrame({"prev": prev, "curr": curr}).fillna(0.0)
    merged["delta"] = merged["curr"] - merged["prev"]
    merged = merged.reindex(merged["delta"].abs().sort_values(ascending=False).index).head(top_n)
    merged = merged.reset_index().rename(columns={"index": group_col})
    merged["Change"] = merged["delta"].apply(lambda v: f"▲ +${v:,.0f}" if v >= 0 else f"▼ -${abs(v):,.0f}")
    return merged, curr_m, prev_m, skipped_partial


def compare_periods_by_group(
    df: pd.DataFrame, date_col: str, group_col: str, value_col: str,
    range_a: tuple, range_b: tuple, top_n: int = 10,
) -> pd.DataFrame | None:
    """Like month_over_month_movers, but for two arbitrary custom date ranges instead
    of the two most recent calendar months — range_a/range_b are (start_ts, end_ts)
    tuples. Returns a DataFrame with columns [group_col, "period_a", "period_b",
    "delta"], the top_n rows by |delta|, or None if there's no data in either range."""
    a_start, a_end = range_a
    b_start, b_end = range_b
    d = df.dropna(subset=[date_col, group_col])
    a = d[(d[date_col] >= a_start) & (d[date_col] <= a_end)].groupby(group_col)[value_col].sum()
    b = d[(d[date_col] >= b_start) & (d[date_col] <= b_end)].groupby(group_col)[value_col].sum()
    if a.empty and b.empty:
        return None
    merged = pd.DataFrame({"period_a": a, "period_b": b}).fillna(0.0)
    merged["delta"] = merged["period_b"] - merged["period_a"]
    merged = merged.reindex(merged["delta"].abs().sort_values(ascending=False).index).head(top_n)
    return merged.reset_index().rename(columns={"index": group_col})


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
    # color_map_for runs out of palette after 8 categories; with >8 years of history
    # the current year would fall through to the muted grey, defeating the whole
    # "this year stands out" design. Pin it to the primary accent.
    year_colors[current_year] = palette["categorical"][0]
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


def save_po_edit(po_id: int, header: dict, items: list[dict],
                 removed_items: list[dict] | None = None) -> tuple[bool, str]:
    """Writes a manual edit straight to Postgres and marks the PO as edited so
    sync_dashboard.py never overwrites it again (see its ON CONFLICT ... WHERE clause).

    `items` are the active line items from the editor; `removed_items` are the PO's
    previously is_removed=TRUE rows, re-persisted verbatim so an edit doesn't
    resurrect them. `additional_cost` / `sku` are carried through — dropping
    additional_cost would make math_check flag lines with a legitimate per-unit
    surcharge. Returns (math_check_failed, math_check_detail) for the caller to show.
    """
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
                        quantity, unit_price, line_total, additional_cost, sku, is_sample,
                        math_mismatch, revision_status, is_removed
                    ) VALUES (
                        %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
                        %(quantity)s, %(unit_price)s, %(line_total)s, %(additional_cost)s, %(sku)s, %(is_sample)s,
                        %(math_mismatch)s, 'Edited', FALSE
                    )
                    """,
                    {
                        "po_id": po_id,
                        "product_raw": item.get("product_raw") or item.get("product_name"),
                        "product_name": item.get("product_name"),
                        "container_size": item.get("container_size"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("unit_price"),
                        "line_total": item.get("line_total"),
                        "additional_cost": item.get("additional_cost"),
                        "sku": item.get("sku"),
                        "is_sample": bool(item.get("is_sample", False)),
                        "math_mismatch": item.get("math_mismatch"),
                    },
                )
            for item in removed_items or []:
                cur.execute(
                    """
                    INSERT INTO line_items (
                        po_id, product_raw, product_name, container_size,
                        quantity, unit_price, line_total, additional_cost, sku, is_sample,
                        math_mismatch, price_anomaly, revision_status, is_removed
                    ) VALUES (
                        %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
                        %(quantity)s, %(unit_price)s, %(line_total)s, %(additional_cost)s, %(sku)s, %(is_sample)s,
                        %(math_mismatch)s, %(price_anomaly)s, %(revision_status)s, TRUE
                    )
                    """,
                    {
                        "po_id": po_id,
                        "product_raw": item.get("product_raw") or item.get("product_name"),
                        "product_name": item.get("product_name"),
                        "container_size": item.get("container_size"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("unit_price"),
                        "line_total": item.get("line_total"),
                        "additional_cost": item.get("additional_cost"),
                        "sku": item.get("sku"),
                        "is_sample": bool(item.get("is_sample", False)),
                        "math_mismatch": item.get("math_mismatch"),
                        "price_anomaly": item.get("price_anomaly"),
                        "revision_status": item.get("revision_status"),
                    },
                )
        conn.commit()
    finally:
        conn.close()
    return bool(data["math_check_failed"]), data["math_check_detail"] or ""


def delete_reference_prices(keys: list[tuple[str, str, str]]) -> None:
    """Removes reference-price rows by (customer_name, product_name, container_size).
    Used when a row is deleted in the Reference Prices editor — without this the
    editor's delete control silently no-ops. An 'auto' row deleted here will be
    re-created by the next extraction sync if a price is still being paid."""
    if not keys:
        return
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            for cust, prod, size in keys:
                cur.execute(
                    "DELETE FROM reference_prices WHERE customer_name = %s AND product_name = %s "
                    "AND container_size = %s",
                    (cust, prod, size),
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
    business rather than the PO-covered slice of it. Invoices a human excluded
    (hidden_invoices — phantom recurring auto-invoices) are dropped here, so they
    never reach any analytics page."""
    conn = psycopg2.connect(get_database_url())
    try:
        # email_status / recur_ref / hidden_invoices land with migration 0012 — fall
        # back to the plain read until the schema catches up.
        try:
            inv_df = pd.read_sql_query(
                "SELECT id, qbo_invoice_id, doc_number, customer_name, txn_date, "
                "ship_date, total_amt, private_note, email_status, delivered_at, "
                "balance, recur_ref FROM qbo_invoices "
                "WHERE qbo_invoice_id NOT IN (SELECT qbo_invoice_id FROM hidden_invoices)",
                conn,
            )
        except Exception:
            conn.rollback()
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


@st.cache_data(ttl=300, show_spinner=False)
def load_donation_totals() -> pd.DataFrame:
    """Every QuickBooks 'donation' line item with its invoice date/customer, read
    straight from the raw tables — NOT gated by prepare_invoices()'s void/zero-total
    filter. Donations are almost always booked on a $0 invoice (a product line plus an
    offsetting negative 'donation' line that nets the invoice to zero), and that filter
    drops such invoices whole, so f_inv_lines can't see them. `donation_amount` is the
    line total sign-flipped to a positive contribution."""
    conn = psycopg2.connect(get_database_url())
    try:
        df = pd.read_sql_query(
            "SELECT ii.invoice_id, inv.customer_name, inv.txn_date, inv.private_note, "
            "-ii.line_total AS donation_amount "
            "FROM qbo_invoice_items ii JOIN qbo_invoices inv ON inv.id = ii.invoice_id "
            "WHERE ii.category = 'donation'",
            conn,
        )
    finally:
        conn.close()
    df = df[~df["private_note"].fillna("").str.contains("void", case=False)].copy()
    df["effective_date"] = pd.to_datetime(df["txn_date"], errors="coerce")
    return df.drop(columns=["private_note"])


@st.cache_data(ttl=300, show_spinner=False)
def load_match_anomalies() -> pd.DataFrame:
    """Confirmed PO<->invoice links that look wrong and should be re-verified: the
    two sides' customers don't correspond, or the dates are implausibly far apart
    (real matches land within a couple of weeks — see
    qbo_matcher._calibrated_date_window). `run_matching` won't create these any more
    (it pre-filters candidates by customer), but historical/manual links can be
    wrong, and a bad `po_date` from extraction surfaces here too. Amount differences
    are deliberately NOT flagged — shipped ≠ requested is normal and is what Order
    Lifecycle reports on."""
    conn = psycopg2.connect(get_database_url())
    try:
        df = pd.read_sql_query(
            """
            SELECT po.id AS po_id, inv.id AS invoice_id, l.match_method,
                   po.po_number, po.customer_name AS po_customer,
                   COALESCE(po.po_date, po.sent_date::date) AS po_date, po.total AS po_total,
                   inv.doc_number, inv.customer_name AS invoice_customer,
                   inv.txn_date AS invoice_date, inv.total_amt AS invoice_total
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
    finally:
        conn.close()
    if df.empty:
        return df
    df["po_date"] = pd.to_datetime(df["po_date"], errors="coerce")
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    df["po_total"] = pd.to_numeric(df["po_total"], errors="coerce")
    df["invoice_total"] = pd.to_numeric(df["invoice_total"], errors="coerce")
    df["day_gap"] = (df["invoice_date"] - df["po_date"]).abs().dt.days

    cust_mismatch = ~df.apply(
        lambda r: customers_match(r["po_customer"], r["invoice_customer"]), axis=1
    )
    date_far = df["day_gap"].fillna(0) > 120

    df["reason"] = ""
    df.loc[cust_mismatch, "reason"] += "customer; "
    df.loc[date_far, "reason"] += "date gap; "
    df = df[df["reason"] != ""].copy()
    df["reason"] = df["reason"].str.rstrip("; ")
    return df.sort_values("day_gap", ascending=False, na_position="last")


@st.cache_data(ttl=300, show_spinner=False)
def load_invoice_reconciliation() -> pd.DataFrame:
    """QBO invoices whose header total_amt doesn't equal the sum of their line items
    (beyond a 2¢ tolerance), or that carry a non-zero total but no line items at all.
    QuickBooks-side data quirks — surfaced on the Data Quality page so the line-item
    revenue views (Products, Explore) can be reconciled against gross invoiced."""
    conn = psycopg2.connect(get_database_url())
    try:
        df = pd.read_sql_query(
            """
            SELECT i.doc_number, i.customer_name, i.txn_date, i.total_amt, i.private_note,
                   COALESCE(s.li_sum, 0)  AS line_items_sum,
                   COALESCE(s.n_lines, 0) AS n_lines
            FROM qbo_invoices i
            LEFT JOIN (
                SELECT invoice_id, SUM(line_total) AS li_sum, COUNT(*) AS n_lines
                FROM qbo_invoice_items GROUP BY invoice_id
            ) s ON s.invoice_id = i.id
            WHERE i.total_amt IS NOT NULL AND i.total_amt <> 0
            """,
            conn,
        )
    finally:
        conn.close()
    df = df[~df["private_note"].fillna("").str.contains("void", case=False)].copy()
    df["total_amt"] = pd.to_numeric(df["total_amt"], errors="coerce")
    df["line_items_sum"] = pd.to_numeric(df["line_items_sum"], errors="coerce")
    df["difference"] = (df["total_amt"] - df["line_items_sum"]).round(2)
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce")
    df = df[df["difference"].abs() > 0.02].drop(columns=["private_note"])
    return df.reindex(df["difference"].abs().sort_values(ascending=False).index)


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
    "po_id", "invoice_id", "customer_name", "customer_canonical", "effective_date",
    "product_name", "container_size", "requested_qty", "requested_amount",
    "delivered_qty", "delivered_amount", "po_math_note",
]


def _norm_product(name) -> str:
    """Punctuation- and case-insensitive product key. The two sides normalise names
    differently (extraction vs product_catalog.classify_qbo_item), so "Bull's Blood
    Beets" / "Bulls Blood Beets" must still align."""
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


# ── Revision grouping (shared identity of "one order" across its versions) ─────
# Mirrors extract_pos.annotate_revisions so the analytics group revisions the way
# the pipeline does: a human "revision of X" / "standalone" review decision is
# authoritative, then a shared Gmail thread (a thread = one order conversation),
# then a shared PO number, then the source file. Used by _choose_revision (the
# line-level requested-vs-shipped basis) and prepare() (the per-order waterfall)
# so both agree — and so requested value is counted once per order, not once per
# revision row or once per linked invoice.


@st.cache_data(ttl=300)
def _load_revision_overrides() -> dict:
    """{target_key: {"revision_of", "standalone"}} from human review decisions."""
    conn = psycopg2.connect(get_database_url())
    try:
        return extraction_reviews.group_override_map(conn)
    finally:
        conn.close()


def _po_target_key(row) -> str:
    tid = row.get("gmail_thread_id")
    return str(tid) if tid not in (None, "") else str(row.get("source_file") or "")


def _base_group_key(row, overrides: dict) -> str:
    ov = overrides.get(_po_target_key(row))
    pid = row.get("id", row.get("po_id"))
    if ov and ov.get("standalone"):
        return f"solo:{pid}"
    if ov and ov.get("revision_of"):
        return f"n:{ov['revision_of']}"
    tid = row.get("gmail_thread_id")
    if tid not in (None, ""):
        return f"t:{tid}"
    num = row.get("po_number")
    if num not in (None, ""):
        return f"n:{num}"
    return f"f:{row.get('source_file') or pid}"


def revision_group_keys(po_df: pd.DataFrame, overrides: dict) -> dict:
    """{po_id -> group key} for every row in po_df. A couple of remap rounds fold
    an overridden row onto its target's key even when the target's own base key is
    t:<thread> rather than n:<number>."""
    id_col = "id" if "id" in po_df.columns else "po_id"
    recs = po_df.to_dict("records")
    key = {int(r[id_col]): _base_group_key(r, overrides) for r in recs}
    for _ in range(4):
        num_key: dict = {}
        for r in recs:
            n = r.get("po_number")
            if n not in (None, ""):
                num_key.setdefault(str(n), key[int(r[id_col])])
        changed = False
        for r in recs:
            ov = overrides.get(_po_target_key(r))
            tgt = ov and ov.get("revision_of")
            if tgt and str(tgt) in num_key and key[int(r[id_col])] != num_key[str(tgt)]:
                key[int(r[id_col])] = num_key[str(tgt)]
                changed = True
        if not changed:
            break
    return key


def _choose_revision(links, cand_pos, group_of):
    """For each order group with more than one candidate revision, "requested" is
    the LATEST revision actually received — po_recency() (document_printed_at >
    source_received_at > sent_date > po_date) — full stop, never whichever
    revision's own numbers happen to fit what was actually shipped. That
    quantity-matching approach (the previous version of this function) was
    circular: a revision that resembles the invoice always LOOKS like a clean
    fulfilment, which is exactly backwards when the real, later revision is the
    one that should be compared against what shipped to see whether it was
    actually honoured. Ties (identical recency, e.g. two rows missing a precise
    timestamp) fall back to the originally-linked row. Every link in the group
    then takes the requested side from that one revision, so a PO number split
    across two invoices (or two revision rows) counts its request once. Groups
    with a single candidate keep each link's own row.

    `group_of`: {po_id -> group key} from revision_group_keys()."""
    rec = {r.po_id: po_recency(r._asdict()) for r in cand_pos.itertuples(index=False)}

    cands_by_group: dict = {}
    for r in cand_pos.itertuples(index=False):
        cands_by_group.setdefault(group_of.get(r.po_id), []).append(r.po_id)

    out = links.copy()
    out["_group"] = out["po_id"].map(group_of)

    chosen_for_group: dict = {}
    for grp, grp_links in out.groupby("_group", dropna=False):
        cands = cands_by_group.get(grp) or list(grp_links["po_id"].unique())
        if len(cands) <= 1:
            continue
        orig = set(grp_links["po_id"])
        best = max(cands, key=lambda pid: (rec.get(pid, po_recency({})), pid in orig))
        chosen_for_group[grp] = best

    out["po_id"] = [
        chosen_for_group.get(g, pid) for g, pid in zip(out["_group"], out["po_id"])
    ]
    return out


@st.cache_data(ttl=300, show_spinner="Loading requested vs. delivered detail...")
def load_matched_line_items() -> pd.DataFrame:
    """Line-item-level requested-vs-delivered detail for every CONFIRMED PO<->invoice
    match — one row per (po_id, invoice_id, product). PO and invoice line items aren't
    linked 1:1 (only the PO<->invoice pair is), so this reconstructs the comparison:
    group each side's items by (id, normalised product), then outer-merge so a product
    requested-but-not-delivered (or vice versa) gets its own row with a zero on the
    missing side.

    Matched on product NAME only, not name+size: ~9% of PO lines (customer emails
    that just say "120 Rainbow Mix") carry no container_size, and the two sides
    spell sizes differently ("4 oz" vs "4oz") — keeping size in the join key split
    one product into a phantom requested-only + delivered-only pair, inflating both
    the shortfall and the overage. Size is kept for display (from the invoice)."""
    conn = psycopg2.connect(get_database_url())
    try:
        links = pd.read_sql_query(
            """
            SELECT l.po_id, l.invoice_id, po.po_number, po.gmail_thread_id, po.source_file,
                   po.customer_name, po.po_date, po.sent_date,
                   inv.customer_name AS customer_canonical
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            LEFT JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE
            """,
            conn,
        )
        if links.empty:
            return pd.DataFrame(columns=_MATCHED_ITEMS_COLUMNS)

        invoice_ids = links["invoice_id"].unique().tolist()
        # ALL revisions of the linked PO numbers (+ the linked rows themselves for
        # NULL-po_number / conversational orders) — the requested side is taken from
        # the LATEST revision actually received (_choose_revision), not blindly
        # whichever row a PO-number match happened to link.
        po_numbers = [n for n in links["po_number"].dropna().unique().tolist()]
        po_ids = links["po_id"].unique().tolist()
        thread_ids = links["gmail_thread_id"].dropna().unique().tolist() if "gmail_thread_id" in links.columns else []
        cand_pos = pd.read_sql_query(
            """
            SELECT po.id AS po_id, po.po_number, po.gmail_thread_id, po.source_file,
                   po.document_printed_at, po.source_received_at, po.sent_date, po.po_date
            FROM purchase_orders po
            WHERE po.error IS NULL AND COALESCE(po.status, 'active') = 'active'
              AND (po.po_number = ANY(%(nums)s) OR po.id = ANY(%(ids)s)
                   OR po.gmail_thread_id = ANY(%(tids)s))
            """,
            conn, params={"nums": po_numbers, "ids": po_ids, "tids": thread_ids},
        )
        po_items = pd.read_sql_query(
            "SELECT po_id, product_name, container_size, quantity, line_total, math_mismatch "
            "FROM line_items "
            "WHERE po_id = ANY(%(ids)s) AND is_sample = FALSE AND is_removed = FALSE",
            conn, params={"ids": cand_pos["po_id"].tolist()},
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

    po_items["_pk"] = po_items["product_name"].map(_norm_product)
    inv_items["_pk"] = inv_items["product_name"].map(_norm_product)

    group_of = revision_group_keys(cand_pos, _load_revision_overrides())
    links = _choose_revision(links, cand_pos, group_of)
    # `customer_canonical` = the linked QBO invoice's customer — the single real
    # entity behind the many PO-side spellings ("Get Fresh", "Get Fresh Produce,
    # LLC.", …). Group customer views on this, not the raw extracted name.
    links["customer_canonical"] = links["customer_canonical"].fillna(links["customer_name"])
    links = links[["po_id", "_group", "invoice_id", "customer_name", "customer_canonical", "effective_date"]]

    def _first_real(s):
        return next((x for x in s if x is not None and str(x).strip()), None)

    po_grouped = po_items.groupby(["po_id", "_pk"], as_index=False).agg(
        po_product=("product_name", _first_real),
        requested_qty=("quantity", "sum"), requested_amount=("line_total", "sum"),
        po_math_note=("math_mismatch", lambda s: next((x for x in s if x), None)),
    )
    inv_grouped = inv_items.groupby(["invoice_id", "_pk"], as_index=False).agg(
        inv_product=("product_name", _first_real),
        container_size=("container_size", _first_real),
        delivered_qty=("quantity", "sum"), delivered_amount=("line_total", "sum"),
    )

    po_side = links.merge(po_grouped, on="po_id", how="left")
    inv_side = links.merge(inv_grouped, on="invoice_id", how="left")

    combined = pd.merge(
        po_side, inv_side,
        on=["po_id", "_group", "invoice_id", "customer_name", "customer_canonical", "effective_date", "_pk"],
        how="outer",
    )
    for col in ("requested_qty", "requested_amount", "delivered_qty", "delivered_amount"):
        combined[col] = combined[col].fillna(0.0)
    combined["product_name"] = combined["po_product"].fillna(combined["inv_product"]).fillna(combined["_pk"])

    # An order's requested-side rows are fanned out once per linked invoice (and,
    # for a PO number split across revision rows, once per revision). Keep the
    # requested amounts on the FIRST row per (order group, product) only — so a
    # sum of this frame counts each order's request exactly once, while delivered
    # still sums across every linked invoice. Split shipments / manual multi-links
    # rely on this; every requested-vs-delivered aggregation sums these columns.
    combined = combined.sort_values(["_group", "_pk", "po_id", "invoice_id"])
    dup = combined.duplicated(subset=["_group", "_pk"], keep="first")
    combined.loc[dup, ["requested_qty", "requested_amount"]] = 0.0
    combined.loc[dup, "po_math_note"] = None
    return combined[_MATCHED_ITEMS_COLUMNS].reset_index(drop=True)


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


@st.cache_data(ttl=300, show_spinner=False)
def load_hidden_customers() -> set[str]:
    """Invoice customer_name values excluded from every analytics page (the
    customer analogue of load_hidden_products; hidden_customers, 0008)."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT customer_name FROM hidden_customers")
            return {row[0] for row in cur.fetchall()}
    except psycopg2.Error:
        conn.rollback()
        return set()
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


_SAVED_VIEWS_DDL = """
CREATE TABLE IF NOT EXISTS dashboard_saved_views (
    name TEXT PRIMARY KEY, kind TEXT NOT NULL, config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


@st.cache_data(ttl=30, show_spinner=False)
def load_saved_views(kind: str) -> list[dict]:
    """[{name, config}] for a page's saved views, oldest first. Returns [] if the
    table doesn't exist yet (it's created lazily by save_view / a schema apply)."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, config FROM dashboard_saved_views WHERE kind = %s ORDER BY created_at", (kind,))
            return [{"name": n, "config": c} for n, c in cur.fetchall()]
    except psycopg2.Error:
        conn.rollback()
        return []
    finally:
        conn.close()


def save_view(kind: str, name: str, config: dict) -> None:
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute(_SAVED_VIEWS_DDL)
            cur.execute(
                "INSERT INTO dashboard_saved_views (name, kind, config) VALUES (%s, %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET kind = EXCLUDED.kind, config = EXCLUDED.config, created_at = now()",
                (name, kind, json.dumps(config)),
            )
        conn.commit()
    finally:
        conn.close()


def delete_view(name: str) -> None:
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dashboard_saved_views WHERE name = %s", (name,))
        conn.commit()
    finally:
        conn.close()


def prepare(po_df: pd.DataFrame, items_df: pd.DataFrame):
    """Dedupe to the latest version of each PO and join line items to it."""
    po = po_df.copy()
    # po_key = the order-group identity (same rule as _choose_revision, so the
    # per-order waterfall and the line-level gap agree on what "one order" is:
    # human revision-of / standalone decision > shared Gmail thread > PO number >
    # source file).
    _id = "id" if "id" in po.columns else "po_id"
    try:
        _gk = revision_group_keys(po, _load_revision_overrides())
        po["po_key"] = po[_id].map(_gk)
    except Exception:  # DB unavailable for the override read — fall back
        po["po_key"] = None
    po["po_key"] = po["po_key"].fillna(po["po_number"]).fillna(po["source_file"])
    po["po_date"] = pd.to_datetime(po["po_date"], errors="coerce")
    po["delivery_date"] = pd.to_datetime(po["delivery_date"], errors="coerce")
    po["effective_date"] = pd.to_datetime(po["sent_date"], errors="coerce").fillna(po["po_date"])
    # Which revision of a po_number is "latest": document_printed_at >
    # source_received_at > sent_date > po_date (qbo_matcher.po_recency). sent_date
    # alone mis-orders a re-extraction that happens to carry one.
    _rec_cols = ["document_printed_at", "source_received_at", "sent_date", "po_date"]
    po["_recency"] = po[[c for c in _rec_cols if c in po.columns]].apply(
        lambda r: po_recency(r.to_dict()), axis=1
    )

    valid_po = po[po["error"].isna()].copy()
    latest_po = (
        valid_po.sort_values(["po_key", "_recency", "id"])
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


# ── Order Lifecycle / Customer 360 helpers (redesign Phase D/E) ───────────────

_LIFECYCLE_COLS = [
    "po_key", "po_number", "source_file", "customer_name", "effective_date",
    "requested_amount", "revised_amount", "shipped_amount", "fulfillment_pct", "po_id",
]


def _lifecycle_rows(vp: pd.DataFrame, matched_items: pd.DataFrame) -> pd.DataFrame:
    """One row per PO (po_key) in `vp`, valued at each stage: requested = the first
    version's header total, revised = the latest version's total, shipped = sum of
    matched invoice line items for that PO. fulfillment_pct = shipped / revised.

    "First"/"last" are ordered by `_recency` (po_recency() — document_printed_at
    > source_received_at > sent_date > po_date) when the caller's frame carries
    it (prepare()'s valid_po always does), the same precise signal both
    prepare()'s own latest_po dedup and _choose_revision() use to pick "the
    latest revision" everywhere else on this page. Previously sorted by
    `effective_date` (sent_date/po_date only — no time-of-day), which for two
    same-day revisions could pick a different "latest" one than the rest of the
    page agrees on — this table's Revised total silently disagreeing with the
    Requested KPI above it for the same order."""
    if vp.empty:
        return pd.DataFrame(columns=_LIFECYCLE_COLS)
    sort_col = "_recency" if "_recency" in vp.columns else "effective_date"
    rows = []
    for po_key, grp in vp.sort_values(["po_key", sort_col, "id"]).groupby("po_key"):
        first, last = grp.iloc[0], grp.iloc[-1]
        rows.append({
            "po_key": po_key, "po_number": last.get("po_number"),
            "source_file": last.get("source_file"), "customer_name": last.get("customer_name"),
            "effective_date": last["effective_date"],
            "requested_amount": first.get("total"), "revised_amount": last.get("total"),
            "po_id": last["id"],
        })
    df = pd.DataFrame(rows)
    if matched_items is not None and not matched_items.empty:
        # Attribute shipped $ by po_key, not just the latest version's po_id: a
        # confirmed PO<->invoice link can sit on an earlier version if a revision
        # landed after the match was confirmed, and keying on last["id"] alone would
        # silently zero that order's shipped value.
        id_to_key = dict(zip(vp["id"], vp["po_key"]))
        mi = matched_items.copy()
        mi["po_key"] = mi["po_id"].map(id_to_key)
        ship = mi.dropna(subset=["po_key"]).groupby("po_key", as_index=False).agg(
            shipped_amount=("delivered_amount", "sum")
        )
        df = df.merge(ship, on="po_key", how="left")
    if "shipped_amount" not in df.columns:
        df["shipped_amount"] = pd.NA
    rev = pd.to_numeric(df["revised_amount"], errors="coerce")
    shp = pd.to_numeric(df["shipped_amount"], errors="coerce")
    df["fulfillment_pct"] = (shp / rev * 100).where(rev > 0).round(1)
    return df.sort_values("effective_date", ascending=False)


def customer_order_lifecycle(
    customer: str, valid_po: pd.DataFrame, matched_items: pd.DataFrame, keep_po_keys=None
) -> pd.DataFrame:
    """`_lifecycle_rows` scoped to one customer (used by Customer 360). Pass
    `keep_po_keys` (the filtered f_po's po_key column) to also honour the page's
    date filter, so the lifecycle KPI/waterfall/table don't silently show all-time
    history while the rest of the page is date-scoped.

    Customer match is containment-based (qbo_matcher.customers_match), not exact:
    the PO table stores short names ("Get Fresh", "Testa Produce") while the picker
    is populated from QBO invoice names ("Get Fresh Produce, Inc.", "Testa Produce
    Inc."), so an exact `==` left this section blank for every PO customer except
    the one whose spelling happened to match on both sides."""
    def _match(series):
        return series.apply(lambda c: customers_match(c, customer))

    vp = valid_po[_match(valid_po["customer_name"])]
    if keep_po_keys is not None:
        vp = vp[vp["po_key"].isin(set(keep_po_keys))]
    if matched_items is not None and not matched_items.empty:
        m = matched_items[_match(matched_items["customer_name"])]
    else:
        m = matched_items
    return _lifecycle_rows(vp, m)


def order_lifecycle(valid_po: pd.DataFrame, keep_po_keys, matched_items: pd.DataFrame) -> pd.DataFrame:
    """`_lifecycle_rows` scoped to a set of po_keys (the filtered orders) — used by
    the Order Lifecycle page for its aggregate + per-order view."""
    return _lifecycle_rows(valid_po[valid_po["po_key"].isin(set(keep_po_keys))], matched_items)


def typical_sizes(customer: str, inv_items: pd.DataFrame) -> pd.DataFrame:
    """For each product this customer buys: the quantity-weighted most common
    container size overall, plus the most common size in the earlier vs. the more
    recent half of their history and whether it changed."""
    d = inv_items[
        (inv_items["customer_name"] == customer)
        & (inv_items["category"] == "product")
        & inv_items["container_size"].notna()
    ].dropna(subset=["effective_date"])
    if d.empty:
        return pd.DataFrame(columns=["product_name", "usual_size", "early_size", "recent_size", "shifted"])

    midpoint = d["effective_date"].median()

    def _mode_size(sub: pd.DataFrame):
        if sub.empty:
            return None
        w = sub.groupby("container_size")["quantity"].sum()
        return w.idxmax() if not w.empty else None

    out = []
    for prod, sub in d.groupby("product_name"):
        early = _mode_size(sub[sub["effective_date"] <= midpoint])
        recent = _mode_size(sub[sub["effective_date"] > midpoint])
        out.append({
            "product_name": prod, "usual_size": _mode_size(sub),
            "early_size": early, "recent_size": recent,
            "shifted": bool(early and recent and early != recent),
        })
    return pd.DataFrame(out).sort_values("product_name")


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

    # Filter state (mirrors the top filter bar — see dashboard/filters.py)
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None
    selected_customers: list = field(default_factory=list)
    selected_products: list = field(default_factory=list)
    include_samples: bool = False

    # Added with the redesign's top filter bar (Phase A). `fs` is the full
    # filters.FilterState; the rest are convenience mirrors. selected_sizes is
    # already applied to f_items / f_inv_items; compare_* and line_types are
    # carried for the pages that consume them in later phases.
    fs: object = None
    selected_sizes: list = field(default_factory=list)
    compare_mode: str = "none"          # "none" | "prev" | "yoy"
    prev_start: pd.Timestamp | None = None
    prev_end: pd.Timestamp | None = None
    line_types: list = field(default_factory=list)

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
    f_inv_items: pd.DataFrame = None          # product(+sample) lines only
    f_inv_lines: pd.DataFrame = None          # every line-type the filter bar has checked

    # Precomputed aggregates (shared across multiple pages)
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


# ── Extraction review queue (training loop) ───────────────────────────────────
#
# Human decisions about what is / isn't a purchase order (and what's a revision of
# what) live in extraction_reviews; the pipeline enforces them, feeds them back as
# few-shot examples, and eval_extraction.py gates on them. See extraction_reviews.py
# and schema.sql. These helpers back dashboard/views/extraction_review.py.

_REVIEW_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS extraction_reviews (
    id SERIAL PRIMARY KEY,
    target_kind TEXT NOT NULL, target_key TEXT NOT NULL,
    content_hash TEXT, content_snapshot TEXT,
    verdict TEXT NOT NULL, revision_of TEXT,
    standalone BOOLEAN NOT NULL DEFAULT FALSE, corrected JSONB,
    fewshot BOOLEAN NOT NULL DEFAULT TRUE,
    reviewer TEXT, note TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_kind, target_key)
);
CREATE TABLE IF NOT EXISTS extraction_snapshots (
    target_kind TEXT NOT NULL, target_key TEXT NOT NULL,
    content TEXT NOT NULL, content_hash TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_kind, target_key)
);
"""


def _ensure_review_tables(cur) -> None:
    cur.execute(_REVIEW_TABLES_DDL)


@st.cache_data(ttl=30, show_spinner=False)
def load_extraction_reviews() -> pd.DataFrame:
    """Every human review decision, newest first."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            _ensure_review_tables(cur)
            conn.commit()
        return pd.read_sql_query(
            "SELECT target_kind, target_key, verdict, revision_of, standalone, "
            "corrected, fewshot, reviewer, note, content_hash, updated_at "
            "FROM extraction_reviews ORDER BY updated_at DESC",
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=120, show_spinner="Building the review queue...")
def load_review_queue(limit: int = 300) -> pd.DataFrame:
    """Extraction results most worth a human look, ranked by how suspect they are.
    Excludes targets that already carry a decision whose content_hash still matches
    the current snapshot (a settled call). Columns: target_kind, target_key,
    po_id, reason, priority, customer_name, po_date, n_items, subject, from_addrs,
    gmail_url, snapshot, decided (bool), stale (bool)."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            _ensure_review_tables(cur)
            conn.commit()
        q = """
        WITH li AS (
            SELECT po_id, count(*) FILTER (WHERE NOT is_removed) AS n_items,
                   count(*) FILTER (WHERE math_mismatch IS NOT NULL AND NOT is_removed) AS n_math
            FROM line_items GROUP BY po_id
        )
        SELECT
            po.id                              AS po_id,
            COALESCE(po.gmail_thread_id, '')   AS thread_id,
            po.source_file, po.error, po.customer_name, po.po_date,
            COALESCE(li.n_items, 0)            AS n_items,
            COALESCE(li.n_math, 0)             AS n_math,
            po.math_check_failed,
            m.subject, m.from_addrs, m.url     AS gmail_url,
            r.verdict                          AS decided_verdict,
            r.content_hash                     AS decided_hash,
            s.content                          AS snapshot,
            s.content_hash                     AS snapshot_hash
        FROM purchase_orders po
        LEFT JOIN li ON li.po_id = po.id
        LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
        LEFT JOIN extraction_reviews r
               ON (r.target_kind = 'thread' AND r.target_key = po.gmail_thread_id)
               OR (r.target_kind = 'file'   AND r.target_key = po.source_file)
        LEFT JOIN extraction_snapshots s
               ON (s.target_kind = 'thread' AND s.target_key = po.gmail_thread_id)
               OR (s.target_kind = 'file'   AND s.target_key = po.source_file)
        WHERE po.gmail_thread_id IS NOT NULL
        """
        df = pd.read_sql_query(q, conn)
    finally:
        conn.close()

    if df.empty:
        return df

    df["target_kind"] = df["source_file"].str.startswith("gmail-thread:").map({True: "thread", False: "file"})
    df["target_key"] = df.apply(
        lambda r: r["thread_id"] if r["target_kind"] == "thread" and r["thread_id"] else r["source_file"], axis=1
    )
    df["decided"] = df["decided_verdict"].notna()
    df["stale"] = df["decided"] & df["decided_hash"].notna() & (df["decided_hash"] != df["snapshot_hash"])

    is_clean = df["error"].isna() | (df["error"] == "")
    reasons, prio = [], []
    for _, r in df.iterrows():
        why, p = [], 0
        err = str(r["error"] or "")
        if err.startswith("modification"):
            why.append("unresolved modification — link it to a PO"); p += 7
        if is_clean[r.name] and r["n_items"] == 0:
            why.append("0 line items"); p += 5
        if is_clean[r.name] and not r["customer_name"]:
            why.append("no customer"); p += 3
        if r["n_math"] > 0 or r["math_check_failed"]:
            why.append("math mismatch"); p += 4
        if r["stale"]:
            why.append("decision is stale (content changed)"); p += 6
        reasons.append(", ".join(why))
        prio.append(p)
    df["reason"], df["priority"] = reasons, prio

    # Keep: anything with a reason and no settled decision, plus every stale one.
    keep = (df["priority"] > 0) & (~df["decided"] | df["stale"])
    df = df[keep].sort_values(["priority", "po_date"], ascending=[False, False]).head(limit)
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner="Finding possible revisions...")
def load_revision_candidates(limit: int = 150) -> pd.DataFrame:
    """High-precision "is B a revision of A?" candidates: two clean POs from the
    same customer with the SAME delivery_date but different po_number, not already
    grouped as revisions and not already decided. A shared delivery date with a
    different PO number is the strong signal — you don't get two separate
    deliveries on one day; a revised PO keeps the delivery date. The line-item
    diff is left for the reviewer. Columns: a_po_id, b_po_id, customer_name,
    delivery_date, a_po_number, b_po_number, a_kind, a_key, b_kind, b_key."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            _ensure_review_tables(cur)
        conn.commit()
        rows = pd.read_sql_query(
            """
            SELECT id AS po_id, customer_name, delivery_date, po_date, po_number,
                   is_revision, source_file, gmail_thread_id
            FROM purchase_orders
            WHERE (error IS NULL OR error = '')
              AND customer_name IS NOT NULL
              AND delivery_date IS NOT NULL
              AND delivery_date > (now() - interval '18 months')
            """,
            conn,
        )
        decided = pd.read_sql_query("SELECT target_kind, target_key FROM extraction_reviews", conn)
    finally:
        conn.close()

    if rows.empty:
        return rows

    decided_keys = set(zip(decided["target_kind"], decided["target_key"])) if not decided.empty else set()
    _is_thread = rows["source_file"].str.startswith("gmail-thread:")
    rows["target_kind"] = _is_thread.map({True: "thread", False: "file"})
    rows["target_key"] = rows["gmail_thread_id"].where(_is_thread, rows["source_file"])
    rows["po_date"] = pd.to_datetime(rows["po_date"])

    out = []
    for (cust, dd), g in rows.groupby(["customer_name", "delivery_date"]):
        recs = g.sort_values("po_date").to_dict("records")
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                if (a["po_number"] or "") == (b["po_number"] or ""):
                    continue
                if a.get("is_revision") and b.get("is_revision"):
                    continue
                if (b["target_kind"], b["target_key"]) in decided_keys:
                    continue
                out.append({
                    "a_po_id": a["po_id"], "b_po_id": b["po_id"], "customer_name": cust,
                    "delivery_date": pd.Timestamp(dd).date(),
                    "a_po_number": a["po_number"], "b_po_number": b["po_number"],
                    # the key annotate_revisions() groups A under: po_number or _source_file
                    "a_group_key": a["po_number"] or a["source_file"],
                    "a_kind": a["target_kind"], "a_key": a["target_key"],
                    "b_kind": b["target_kind"], "b_key": b["target_key"],
                })
    df = pd.DataFrame(out)
    if df.empty:
        return df
    return df.sort_values("delivery_date", ascending=False).head(limit).reset_index(drop=True)


def save_extraction_review(
    *, target_kind: str, target_key: str, verdict: str,
    revision_of: str | None = None, standalone: bool = False,
    corrected: dict | None = None, note: str | None = None, reviewer: str | None = None,
) -> None:
    """Persist a decision, snapshot the content it was made on, and reconcile the
    stored PO rows for that target so the dashboard reflects the call immediately."""
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            _ensure_review_tables(cur)
        conn.commit()
        snap = extraction_reviews.get_decision  # noqa: F841 (keep import used even if unref)
        snapshot = None
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT content, content_hash FROM extraction_snapshots "
                "WHERE target_kind = %s AND target_key = %s",
                (target_kind, target_key),
            )
            snapshot = cur.fetchone()

        extraction_reviews.upsert_decision(
            conn,
            target_kind=target_kind, target_key=target_key, verdict=verdict,
            content_hash=(snapshot or {}).get("content_hash"),
            content_snapshot=(snapshot or {}).get("content"),
            revision_of=revision_of, standalone=standalone,
            corrected=corrected, reviewer=reviewer, note=note,
        )

        # Reconcile stored purchase_orders rows so the rest of the dashboard agrees
        # with the call right now (the pipeline would also do this on its next run).
        with conn.cursor() as cur:
            if target_kind == "thread":
                where = "(gmail_thread_id = %s OR source_file = %s)"
                params = (target_key, f"gmail-thread:{target_key}")
            else:
                where = "source_file = %s"
                params = (target_key,)
            if verdict == "not_po":
                cur.execute(
                    f"UPDATE purchase_orders SET error = 'not a purchase order' "
                    f"WHERE {where} AND (error IS NULL OR error = '')",
                    params,
                )
            elif verdict == "is_po":
                cur.execute(
                    f"UPDATE purchase_orders SET error = NULL "
                    f"WHERE {where} AND error = 'not a purchase order'",
                    params,
                )
        conn.commit()
    finally:
        conn.close()

    for fn in (load_extraction_reviews, load_review_queue, load_revision_candidates, load_data):
        try:
            fn.clear()
        except Exception:
            pass


def delete_extraction_review(target_kind: str, target_key: str) -> None:
    conn = psycopg2.connect(get_database_url())
    try:
        extraction_reviews.delete_decision(conn, target_kind, target_key)
    finally:
        conn.close()
    for fn in (load_extraction_reviews, load_review_queue, load_revision_candidates):
        try:
            fn.clear()
        except Exception:
            pass
