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

def test_choose_revision_picks_one_per_group_against_combined_invoices():
    links = _df([{"po_id": 10, "invoice_id": 100}, {"po_id": 10, "invoice_id": 101}])
    cand_pos = _df([
        {"po_id": 10, "po_number": "1", "gmail_thread_id": None, "source_file": "o.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-01", "po_date": "2026-01-01"},
        {"po_id": 11, "po_number": "1", "gmail_thread_id": None, "source_file": "r.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-05", "po_date": "2026-01-05"},
    ])
    po_items = _df([
        {"po_id": 10, "product_name": "Arugula", "quantity": 100},  # original ask
        {"po_id": 11, "product_name": "Arugula", "quantity": 60},   # revised down
    ])
    po_items["_pk"] = po_items["product_name"].map(_dash._norm_product)
    inv_items = _df([
        {"invoice_id": 100, "product_name": "Arugula", "quantity": 30},
        {"invoice_id": 101, "product_name": "Arugula", "quantity": 30},  # 60 total -> matches rev
    ])
    inv_items["_pk"] = inv_items["product_name"].map(_dash._norm_product)

    out = _dash._choose_revision(links, cand_pos, po_items, inv_items, {10: "n:1", 11: "n:1"})
    assert set(out["po_id"]) == {11}
    assert list(out["_group"]) == ["n:1", "n:1"]


def test_choose_revision_single_candidate_group_is_left_alone():
    links = _df([{"po_id": 10, "invoice_id": 100}])
    cand_pos = _df([
        {"po_id": 10, "po_number": "1", "gmail_thread_id": None, "source_file": "o.pdf",
         "document_printed_at": None, "source_received_at": None,
         "sent_date": "2026-01-01", "po_date": "2026-01-01"},
    ])
    po_items = _df([{"po_id": 10, "product_name": "Arugula", "quantity": 100, "_pk": "arugula"}])
    inv_items = _df([{"invoice_id": 100, "product_name": "Arugula", "quantity": 40, "_pk": "arugula"}])
    out = _dash._choose_revision(links, cand_pos, po_items, inv_items, {10: "n:1"})
    assert list(out["po_id"]) == [10]
