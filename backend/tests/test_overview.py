"""Overview KPI sparklines — the pure trailing-series helpers. No DB."""

import os

import pandas as pd

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("ALLOWED_EMAIL_DOMAINS", "example.com")

import app.reuse  # noqa: E402,F401 — sys.path shim for the reused repo modules
from app.services.overview import _trailing_ratio  # noqa: E402


def _df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["effective_date"] = pd.to_datetime(df["effective_date"])
    return df


def test_trailing_ratio_is_monthly_sum_over_sum_times_scale():
    df = _df([
        {"effective_date": "2026-01-05", "n": 8, "d": 10},
        {"effective_date": "2026-01-20", "n": 2, "d": 10},   # Jan: 10 / 20 -> 50%
        {"effective_date": "2026-02-10", "n": 9, "d": 10},
        {"effective_date": "2026-02-15", "n": 6, "d": 10},   # Feb: 15 / 20 -> 75%
    ])
    assert _trailing_ratio(df, num_col="n", den_col="d") == [50.0, 75.0]


def test_trailing_ratio_drops_zero_denominator_months_and_needs_two_points():
    df = _df([
        {"effective_date": "2026-01-05", "n": 0, "d": 0},    # dropped
        {"effective_date": "2026-02-05", "n": 5, "d": 10},
    ])
    assert _trailing_ratio(df, num_col="n", den_col="d") == []


def test_trailing_ratio_empty_frame():
    empty = pd.DataFrame({"effective_date": pd.to_datetime([]), "n": [], "d": []})
    assert _trailing_ratio(empty, num_col="n", den_col="d") == []
