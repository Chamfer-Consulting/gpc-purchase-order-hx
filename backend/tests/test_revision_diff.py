"""po_admin.diff_versions — the pure header + line diff behind the Edit PO page's
'Compare' view. No DB."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401
from app.services.po_admin import diff_versions  # noqa: E402


def _po(header: dict, items: list[dict]) -> dict:
    return {"header": header, "items": items, "removed_items": []}


def _line(name, size, qty, price, total):
    return {"product_name": name, "container_size": size, "product_raw": name,
            "quantity": qty, "unit_price": price, "line_total": total}


def test_added_removed_changed_and_same():
    a = _po(
        {"po_number": "1001", "total": 30},
        [_line("Arugula", "4oz", 10, 2.0, 20.0), _line("Basil", "2oz", 5, 2.0, 10.0)],
    )
    b = _po(
        {"po_number": "1001", "total": 44},
        [_line("Arugula", "4oz", 12, 2.0, 24.0), _line("Cilantro", "1oz", 10, 2.0, 20.0)],
    )
    d = diff_versions(a, b, a_id=1, b_id=2)
    by = {(r["product"], r["size"]): r["status"] for r in d["rows"]}
    assert by[("Arugula", "4oz")] == "changed"
    assert by[("Basil", "2oz")] == "removed"
    assert by[("Cilantro", "1oz")] == "added"
    assert d["n_changed"] == 3
    assert d["a"]["po_id"] == 1 and d["b"]["n_items"] == 2


def test_identical_lines_report_same_and_zero_changed():
    line = _line("Arugula", "4oz", 10, 2.0, 20.0)
    d = diff_versions(_po({"po_number": "9"}, [line]), _po({"po_number": "9"}, [dict(line)]))
    assert [r["status"] for r in d["rows"]] == ["same"]
    assert d["n_changed"] == 0 and d["header"] == []


def test_header_changes_listed_with_both_sides():
    d = diff_versions(
        _po({"po_number": "1", "po_date": "2026-01-01", "total": 10}, []),
        _po({"po_number": "1", "po_date": "2026-01-03", "total": 12}, []),
    )
    fields = {h["field"]: (h["a"], h["b"]) for h in d["header"]}
    assert fields["po_date"] == ("2026-01-01", "2026-01-03")
    assert fields["total"] == (10, 12)
    assert "po_number" not in fields


def test_null_size_lines_match():
    d = diff_versions(
        _po({}, [_line("Rainbow Mix", None, 100, 1.0, 100.0)]),
        _po({}, [_line("Rainbow Mix", "", 120, 1.0, 120.0)]),
    )
    assert len(d["rows"]) == 1 and d["rows"][0]["status"] == "changed"
