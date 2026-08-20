#!/usr/bin/env python3
"""
Re-run math validation against already-extracted data, without calling the API.

Use this after changing validate_math()'s logic in math_check.py — all the
fields it needs (subtotal, tax, total, line items) are already stored locally,
so past extractions can be re-checked for free.

Usage:
    python recompute_math_checks.py --db po_data.db
"""

import argparse

import db
from math_check import validate_math


def recompute(sqlite_path: str) -> tuple[int, int]:
    conn = db.connect(sqlite_path)
    rows = conn.execute("SELECT * FROM purchase_orders WHERE error IS NULL").fetchall()

    changed = 0
    for row in rows:
        result = db._row_to_result(conn, row)
        was_failed = result["math_check_failed"]
        validate_math(result)
        if result["math_check_failed"] != was_failed or result["math_check_detail"] != row["math_check_detail"]:
            changed += 1
        db.update_math_check(conn, row["id"], result["math_check_failed"], result["math_check_detail"])

    conn.commit()
    conn.close()
    return len(rows), changed


def main():
    parser = argparse.ArgumentParser(description="Recompute math-check flags on already-extracted data")
    parser.add_argument("--db", default="po_data.db", help="Local SQLite database path (default: po_data.db)")
    args = parser.parse_args()

    total, changed = recompute(args.db)
    print(f"Checked {total} record(s); {changed} verdict(s) changed.")


if __name__ == "__main__":
    main()
