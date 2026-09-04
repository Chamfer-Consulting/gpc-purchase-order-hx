"""shared/data.py revision grouping — the identity of "one order" across its
extracted versions, and choosing one revision per group for the requested side.
Pure functions, no DB."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401 — repo root + shared/ on sys.path
import pandas as pd  # noqa: E402
import data as _dash  # noqa: E402


def _df(rows):
    return pd.DataFrame(rows)


# ── revision_group_keys ──────────────────────────────────────────────────────

def test_group_by_po_number():
    df = _df([
        {"id": 1, "po_number": "1234", "gmail_thread_id": None, "source_file": "a.pdf"},
        {"id": 2, "po_number": "1234", "gmail_thread_id": None, "source_file": "b.pdf"},
        {"id": 3, "po_number": "9999", "gmail_thread_id": None, "source_file": "c.pdf"},
    ])
    k = _dash.revision_group_keys(df, {})
    assert k[1] == k[2] and k[1] != k[3]


def test_group_by_gmail_thread_even_with_a_changed_or_missing_number():
    df = _df([
        {"id": 1, "po_number": "1234", "gmail_thread_id": "T1", "source_file": "gmail-thread:T1"},
        {"id": 2, "po_number": None, "gmail_thread_id": "T1", "source_file": "gmail-thread:T1#mod"},
        {"id": 3, "po_number": "1234-B", "gmail_thread_id": "T1", "source_file": "x"},
    ])
    k = _dash.revision_group_keys(df, {})
    assert k[1] == k[2] == k[3]


def test_review_override_merges_across_po_numbers():
    df = _df([
        {"id": 1, "po_number": "1234", "gmail_thread_id": None, "source_file": "orig.pdf"},
        {"id": 2, "po_number": "5678", "gmail_thread_id": None, "source_file": "reissue.pdf"},
    ])
    overrides = {"reissue.pdf": {"revision_of": "1234", "standalone": False}}
    k = _dash.revision_group_keys(df, overrides)
    assert k[1] == k[2]


def test_review_override_merges_when_target_row_is_threaded():
    # id 1's base key is t:T9 (thread wins over number); the remap round still
    # folds the overridden id 2 onto it.
    df = _df([
        {"id": 1, "po_number": "1234", "gmail_thread_id": "T9", "source_file": "gmail-thread:T9"},
        {"id": 2, "po_number": "5678", "gmail_thread_id": None, "source_file": "reissue.pdf"},
    ])
    overrides = {"reissue.pdf": {"revision_of": "1234", "standalone": False}}
    k = _dash.revision_group_keys(df, overrides)
    assert k[1] == k[2]


def test_standalone_decision_never_groups():
    df = _df([
        {"id": 1, "po_number": "1234", "gmail_thread_id": None, "source_file": "a.pdf"},
        {"id": 2, "po_number": "1234", "gmail_thread_id": None, "source_file": "b.pdf"},
    ])
    overrides = {"b.pdf": {"revision_of": None, "standalone": True}}
    k = _dash.revision_group_keys(df, overrides)
    assert k[1] != k[2]


def test_no_number_no_thread_falls_back_to_source_file():
    df = _df([
        {"id": 1, "po_number": None, "gmail_thread_id": None, "source_file": "one.pdf"},
        {"id": 2, "po_number": None, "gmail_thread_id": None, "source_file": "two.pdf"},
    ])
    k = _dash.revision_group_keys(df, {})
    assert k[1] != k[2]


# ── _choose_revision ─────────────────────────────────────────────────────────
# "Requested" is the LATEST revision actually received, full stop — never
# whichever revision's own quantities happen to fit what was shipped (that was
# the previous, circular behavior: a revision resembling the invoice always
# looked like a clean fulfilment, which is backwards).

def test_choose_revision_picks_the_latest_even_when_an_earlier_one_fits_better():
    links = _df([{"po_id": 10, "invoice_id": 100}, {"po_id": 10, "invoice_id": 101}])
    cand_pos = _df([
        # po 10: earlier, and its total (30) happens to match what shipped —
        # under the old quantity-matching logic this would have won.
        {"po_id": 10, "po_number": "1", "gmail_thread_id": None, "source_file": "o.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-01", "po_date": "2026-01-01"},
        # po 11: later, revised up — the real final ask, per the customer's own
        # timeline, regardless of how far it is from what actually shipped.
        {"po_id": 11, "po_number": "1", "gmail_thread_id": None, "source_file": "r.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-05", "po_date": "2026-01-05"},
    ])
    out = _dash._choose_revision(links, cand_pos, {10: "n:1", 11: "n:1"})
    assert set(out["po_id"]) == {11}
    assert list(out["_group"]) == ["n:1", "n:1"]


def test_choose_revision_ties_fall_back_to_the_originally_linked_row():
    # Both candidates lack any recency signal (po_recency() -> datetime.min for
    # both) — a real case: missing document_printed_at / source_received_at, the
    # majority of this dataset's rows. The tie must not raise or pick arbitrarily.
    links = _df([{"po_id": 10, "invoice_id": 100}])
    cand_pos = _df([
        {"po_id": 10, "po_number": "1", "gmail_thread_id": None, "source_file": "o.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": None, "po_date": None},
        {"po_id": 11, "po_number": "1", "gmail_thread_id": None, "source_file": "r.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": None, "po_date": None},
    ])
    out = _dash._choose_revision(links, cand_pos, {10: "n:1", 11: "n:1"})
    assert list(out["po_id"]) == [10]


def test_choose_revision_single_candidate_group_is_left_alone():
    links = _df([{"po_id": 10, "invoice_id": 100}])
    cand_pos = _df([
        {"po_id": 10, "po_number": "1", "gmail_thread_id": None, "source_file": "o.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-01", "po_date": "2026-01-01"},
    ])
    out = _dash._choose_revision(links, cand_pos, {10: "n:1"})
    assert list(out["po_id"]) == [10]


# ── _lifecycle_rows ──────────────────────────────────────────────────────────
# The per-order waterfall (Order Lifecycle's "First ask -> Revised -> Shipped"
# table) must pick "latest revision" the same way the rest of the page
# (_choose_revision, prepare()'s own latest_po dedup) does — by `_recency`
# (po_recency()), not by the coarser date-only `effective_date`.

def test_lifecycle_rows_orders_by_recency_not_just_effective_date():
    # Both rows share the same effective_date (same calendar day) — only
    # `_recency` (a precise received-at timestamp on the second row) tells them
    # apart. Sorting by effective_date alone (the old behavior) would fall back
    # to `id`, picking the SMALLER, earlier-created row as "latest" — backwards.
    vp = _df([
        {"po_key": "n:1", "id": 27307, "po_number": "1", "source_file": "o.pdf",
         "customer_name": "Acme", "effective_date": pd.Timestamp("2024-06-27"),
         "total": 100.0, "_recency": pd.Timestamp("2024-06-27 10:57:00")},
        {"po_key": "n:1", "id": 465, "po_number": "1", "source_file": "r.pdf",
         "customer_name": "Acme", "effective_date": pd.Timestamp("2024-06-27"),
         "total": 200.0, "_recency": pd.Timestamp("2024-06-28 13:49:00")},
    ])
    out = _dash._lifecycle_rows(vp, pd.DataFrame())
    row = out.iloc[0]
    assert row["requested_amount"] == 100.0  # first by recency
    assert row["revised_amount"] == 200.0    # last by recency — the real revision
    assert row["po_id"] == 465


def test_lifecycle_rows_falls_back_to_effective_date_without_recency():
    vp = _df([
        {"po_key": "n:1", "id": 10, "po_number": "1", "source_file": "o.pdf",
         "customer_name": "Acme", "effective_date": pd.Timestamp("2024-06-27"), "total": 100.0},
        {"po_key": "n:1", "id": 11, "po_number": "1", "source_file": "r.pdf",
         "customer_name": "Acme", "effective_date": pd.Timestamp("2024-06-28"), "total": 200.0},
    ])
    out = _dash._lifecycle_rows(vp, pd.DataFrame())
    row = out.iloc[0]
    assert row["revised_amount"] == 200.0
