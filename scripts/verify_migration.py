#!/usr/bin/env python3
"""Compare row counts table-by-table between two Postgres databases — used after the
Neon -> Supabase dump/restore (docs/REBUILD-SETUP.md §2).

    python scripts/verify_migration.py "<source_url>" "<target_url>"

Exits 0 if every user table matches, 1 otherwise.
"""

import sys

import psycopg2


def _counts(url: str) -> dict[str, int]:
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            tables = [r[0] for r in cur.fetchall()]
            out = {}
            for t in tables:
                cur.execute(f'SELECT count(*) FROM "{t}"')
                out[t] = cur.fetchone()[0]
        return out
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    src, dst = _counts(sys.argv[1]), _counts(sys.argv[2])

    all_tables = sorted(set(src) | set(dst))
    width = max(len(t) for t in all_tables) if all_tables else 10
    ok = True
    print(f"{'table':<{width}}  {'source':>12}  {'target':>12}  status")
    print("-" * (width + 42))
    for t in all_tables:
        s, d = src.get(t), dst.get(t)
        # Absent on one side counts as 0 — so a table that exists only on the
        # target (a new one added post-cutover) with no rows is fine, while a
        # source table whose rows didn't land is a MISMATCH.
        match = (s or 0) == (d or 0)
        ok = ok and match
        s_txt = "—" if s is None else f"{s:,}"
        d_txt = "—" if d is None else f"{d:,}"
        print(f"{t:<{width}}  {s_txt:>12}  {d_txt:>12}  {'ok' if match else 'MISMATCH'}")

    print()
    if ok:
        print("✅ all tables match")
        sys.exit(0)
    print("❌ mismatch — do not cut over")
    sys.exit(1)


if __name__ == "__main__":
    main()
