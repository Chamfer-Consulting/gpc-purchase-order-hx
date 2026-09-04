"""shared/qbo_client.py's QuickBooks 'Group' (bundle) line flattening — a Group
line's real product content lives in GroupLineDetail.Line[], not on the line
itself. Pure function, no DB."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401 — repo root + shared/ on sys.path
import qbo_client  # noqa: E402


def test_flattens_a_group_line_into_its_nested_sales_item_lines():
    lines = [
        {
            "DetailType": "GroupLineDetail",
            "Amount": 40.0,
            "GroupLineDetail": {
                "Line": [
                    {"Id": "2", "Amount": 40.0, "DetailType": "SalesItemLineDetail",
                     "SalesItemLineDetail": {"Qty": 32, "ItemRef": {"value": "8", "name": "Pea Shoots"}}},
                ],
                "Quantity": 4,
                "GroupItemRef": {"value": "59", "name": "8 oz. Pea Shoots"},
            },
        },
        {"Amount": 40.0, "DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}},
    ]
    out = qbo_client._flatten_group_lines(lines)
    assert len(out) == 2
    assert out[0]["SalesItemLineDetail"]["Qty"] == 32
    assert out[1]["DetailType"] == "SubTotalLineDetail"


def test_ordinary_lines_pass_through_unchanged():
    lines = [
        {"DetailType": "SalesItemLineDetail", "SalesItemLineDetail": {"Qty": 1}},
        {"DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}},
    ]
    assert qbo_client._flatten_group_lines(lines) == lines


def test_none_and_empty_are_safe():
    assert qbo_client._flatten_group_lines(None) == []
    assert qbo_client._flatten_group_lines([]) == []


def test_a_group_line_with_no_nested_lines_contributes_nothing():
    lines = [{"DetailType": "GroupLineDetail", "GroupLineDetail": {}}]
    assert qbo_client._flatten_group_lines(lines) == []
