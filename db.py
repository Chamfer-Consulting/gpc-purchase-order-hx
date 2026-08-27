"""
SQLite persistence for extracted PO data.

Acts as the durable source of truth behind extract_pos.py — the Excel output
is a generated view of this data, not the other way around. Also lets repeat
runs over the same folder skip files that haven't changed since they were
last extracted (matched by content hash, not filename/mtime).
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file        TEXT NOT NULL,
    file_hash          TEXT NOT NULL,
    extraction_method  TEXT,
    error              TEXT,
    po_number          TEXT,
    po_date            TEXT,
    sent_date          TEXT,
    delivery_date      TEXT,
    document_printed_at TEXT,
    source_received_at TEXT,
    revision_number    TEXT,
    revision_label     TEXT,
    customer_name      TEXT,
    customer_id        TEXT,
    subtotal           REAL,
    tax                REAL,
    total              REAL,
    notes              TEXT,
    math_check_failed  INTEGER,
    math_check_detail  TEXT,
    extracted_at       TEXT NOT NULL,
    UNIQUE(source_file, file_hash)
);

CREATE TABLE IF NOT EXISTS line_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_raw     TEXT,
    sku             TEXT,
    quantity        REAL,
    unit_price      REAL,
    additional_cost REAL,
    line_total      REAL,
    product_name    TEXT,
    container_size  TEXT,
    is_sample       INTEGER,
    needs_review    INTEGER,
    math_mismatch   TEXT
);

CREATE INDEX IF NOT EXISTS idx_line_items_po_id ON line_items(po_id);
CREATE INDEX IF NOT EXISTS idx_po_po_number ON purchase_orders(po_number);

-- Expected/current price per (customer, product, size) — the basis for flagging
-- price anomalies on new extractions. Refreshed automatically before each
-- extract_pos.py run from the most recent price actually paid in local history.
CREATE TABLE IF NOT EXISTS reference_prices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name   TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    container_size  TEXT NOT NULL,
    price           REAL NOT NULL,
    source          TEXT NOT NULL DEFAULT 'auto',
    updated_at      TEXT NOT NULL,
    UNIQUE(customer_name, product_name, container_size)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # CREATE TABLE IF NOT EXISTS above is a no-op against an existing older DB —
    # add columns introduced after the initial schema explicitly. (Older SQLite
    # builds don't support "ADD COLUMN IF NOT EXISTS", so check first.)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(line_items)")}
    if "additional_cost" not in cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN additional_cost REAL")
    if "price_anomaly" not in cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN price_anomaly TEXT")
    po_cols = {row[1] for row in conn.execute("PRAGMA table_info(purchase_orders)")}
    if "document_printed_at" not in po_cols:
        conn.execute("ALTER TABLE purchase_orders ADD COLUMN document_printed_at TEXT")
    if "source_received_at" not in po_cols:
        conn.execute("ALTER TABLE purchase_orders ADD COLUMN source_received_at TEXT")
    conn.commit()


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_to_result(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    result = {
        "_source_file": row["source_file"],
        "_file_hash": row["file_hash"],
        "_extraction_method": row["extraction_method"],
        "po_number": row["po_number"],
        "po_date": row["po_date"],
        "sent_date": row["sent_date"],
        "delivery_date": row["delivery_date"],
        "document_printed_at": row["document_printed_at"],
        "source_received_at": row["source_received_at"],
        "revision_number": row["revision_number"],
        "revision_label": row["revision_label"],
        "customer_name": row["customer_name"],
        "customer_id": row["customer_id"],
        "subtotal": row["subtotal"],
        "tax": row["tax"],
        "total": row["total"],
        "notes": row["notes"],
        "math_check_failed": bool(row["math_check_failed"]),
        "math_check_detail": row["math_check_detail"],
        "line_items": [],
    }
    if row["error"] is not None:
        result["error"] = row["error"]

    items = conn.execute("SELECT * FROM line_items WHERE po_id = ? ORDER BY id", (row["id"],)).fetchall()
    for it in items:
        item = {
            "product_raw": it["product_raw"],
            "sku": it["sku"],
            "quantity": it["quantity"],
            "unit_price": it["unit_price"],
            "additional_cost": it["additional_cost"],
            "line_total": it["line_total"],
            "product_name": it["product_name"],
            "container_size": it["container_size"],
            "is_sample": bool(it["is_sample"]),
            "needs_review": bool(it["needs_review"]),
        }
        if it["math_mismatch"]:
            item["math_mismatch"] = it["math_mismatch"]
        if it["price_anomaly"]:
            item["price_anomaly"] = it["price_anomaly"]
        result["line_items"].append(item)

    return result


def get_cached_result(conn: sqlite3.Connection, source_file: str, file_hash: str) -> dict | None:
    """Returns a previously successful extraction for this exact file content, or None."""
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE source_file = ? AND file_hash = ? AND error IS NULL",
        (source_file, file_hash),
    ).fetchone()
    if row is None:
        return None
    return _row_to_result(conn, row)


def get_all_results(conn: sqlite3.Connection) -> list[dict]:
    """Returns every stored extraction (including past errors), for publishing/reporting."""
    rows = conn.execute("SELECT * FROM purchase_orders ORDER BY id").fetchall()
    return [_row_to_result(conn, row) for row in rows]


def save_result(conn: sqlite3.Connection, file_hash: str, result: dict) -> None:
    """Upserts one extraction result, keyed by (source_file, file_hash)."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO purchase_orders (
            source_file, file_hash, extraction_method, error,
            po_number, po_date, sent_date, delivery_date, document_printed_at, source_received_at,
            revision_number, revision_label, customer_name, customer_id,
            subtotal, tax, total, notes,
            math_check_failed, math_check_detail, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.get("_source_file"), file_hash, result.get("_extraction_method"), result.get("error"),
            result.get("po_number"), result.get("po_date"), result.get("sent_date"), result.get("delivery_date"),
            result.get("document_printed_at"), result.get("source_received_at"),
            result.get("revision_number"), result.get("revision_label"),
            result.get("customer_name"), result.get("customer_id"),
            result.get("subtotal"), result.get("tax"), result.get("total"), result.get("notes"),
            int(bool(result.get("math_check_failed"))), result.get("math_check_detail"),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    po_id = cur.lastrowid

    for item in result.get("line_items") or []:
        cur.execute(
            """
            INSERT INTO line_items (
                po_id, product_raw, sku, quantity, unit_price, additional_cost, line_total,
                product_name, container_size, is_sample, needs_review, math_mismatch, price_anomaly
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po_id, item.get("product_raw"), item.get("sku"),
                item.get("quantity"), item.get("unit_price"), item.get("additional_cost"),
                item.get("line_total"),
                item.get("product_name"), item.get("container_size"),
                int(bool(item.get("is_sample"))), int(bool(item.get("needs_review"))),
                item.get("math_mismatch"), item.get("price_anomaly"),
            ),
        )

    conn.commit()


def update_math_check(conn: sqlite3.Connection, po_id: int, failed: bool, detail: str) -> None:
    """Updates only the math-check verdict for an existing row — used when the
    validation logic changes and past extractions need re-checking without
    re-calling the API."""
    conn.execute(
        "UPDATE purchase_orders SET math_check_failed = ?, math_check_detail = ? WHERE id = ?",
        (int(bool(failed)), detail, po_id),
    )


def refresh_reference_prices(conn: sqlite3.Connection) -> None:
    """Recomputes each (customer, product, size)'s reference price as the unit_price
    from the most recent PO (by po_date, then id as a tiebreak) among non-sample,
    non-removed line items on successfully-extracted POs. Called once at the start of
    each extract_pos.py run, before any new extractions, so new prices are always
    compared against everything known prior to this run."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR REPLACE INTO reference_prices
            (customer_name, product_name, container_size, price, source, updated_at)
        SELECT customer_name, product_name, container_size, unit_price, 'auto', ?
        FROM (
            SELECT po.customer_name AS customer_name, li.product_name AS product_name,
                   li.container_size AS container_size, li.unit_price AS unit_price,
                   ROW_NUMBER() OVER (
                       PARTITION BY po.customer_name, li.product_name, li.container_size
                       ORDER BY po.po_date DESC, po.id DESC
                   ) AS rn
            FROM line_items li
            JOIN purchase_orders po ON po.id = li.po_id
            WHERE po.error IS NULL AND li.is_sample = 0
              AND li.unit_price IS NOT NULL AND li.unit_price > 0
              AND po.customer_name IS NOT NULL AND li.product_name IS NOT NULL
              AND li.container_size IS NOT NULL AND li.container_size != ''
        )
        WHERE rn = 1
        """,
        (now,),
    )
    conn.commit()


def get_reference_prices(conn: sqlite3.Connection) -> dict:
    """Returns {(customer_name, product_name, container_size): price} for every
    reference price currently on file."""
    rows = conn.execute("SELECT customer_name, product_name, container_size, price FROM reference_prices").fetchall()
    return {(r["customer_name"], r["product_name"], r["container_size"]): r["price"] for r in rows}


def get_reference_price_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Returns every reference_prices row, for publishing to the dashboard database."""
    return conn.execute(
        "SELECT customer_name, product_name, container_size, price, source FROM reference_prices"
    ).fetchall()
