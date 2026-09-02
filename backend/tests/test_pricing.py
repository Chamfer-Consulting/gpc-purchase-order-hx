"""Price history — the pure delivery-rate inference and trend helpers. No DB."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("ALLOWED_EMAIL_DOMAINS", "example.com")

import app.reuse  # noqa: E402,F401 — sys.path shim for the reused repo modules
from app.services.pricing import (  # noqa: E402
    _STD_BAND_END,
    _STD_BAND_START,
    _build_delivery_rates,
    _delivery_rate,
    _monthly_trend,
)


def _rates(rows):
    return _build_delivery_rates(rows, canon={})


def test_delivery_rate_cascade_customer_year_then_customer_then_global():
    rows = [
        {"customer_name": "Acme", "yr": 2023, "rate": 0.40},
        {"customer_name": "Acme", "yr": 2023, "rate": 0.60},   # (Acme, 2023) median -> 0.50
        {"customer_name": "Acme", "yr": 2024, "rate": 1.00},   # (Acme, 2024) -> 1.00
        {"customer_name": "Beta", "yr": 2023, "rate": 0.30},
    ]
    t = _rates(rows)
    assert _delivery_rate(t, "Acme", 2023) == 0.50
    assert _delivery_rate(t, "Acme", 2024) == 1.00
    # unknown year -> customer median across all Acme rates [0.4, 0.6, 1.0]
    assert _delivery_rate(t, "Acme", 2099) == 0.60
    # unknown customer -> global median across every rate [0.3, 0.4, 0.6, 1.0]
    assert _delivery_rate(t, "Zeta", 2023) == 0.50


def test_delivery_rate_skips_nonpositive_and_none_and_maps_canon():
    rows = [
        {"customer_name": "Acme Inc", "yr": 2024, "rate": 0.5},
        {"customer_name": "Acme Inc", "yr": 2024, "rate": None},   # skipped
        {"customer_name": "Acme Inc", "yr": 2024, "rate": 0.0},    # skipped
        {"customer_name": "Acme Inc", "yr": 2024, "rate": -1.0},   # skipped
    ]
    t = _build_delivery_rates(rows, canon={"Acme Inc": "Acme"})
    assert _delivery_rate(t, "Acme", 2024) == 0.5


def test_delivery_rate_empty_is_zero():
    t = _rates([])
    assert t["global"] == 0.0
    assert _delivery_rate(t, "Anyone", 2025) == 0.0


def test_monthly_trend_medians_per_month_from_band_end():
    pts = [
        {"date": "2024-07-15", "unit_price_adj": 99.0},   # before band end -> excluded
        {"date": "2024-07-31", "unit_price_adj": 5.0},
        {"date": "2024-08-10", "unit_price_adj": 6.0},
        {"date": "2024-08-20", "unit_price_adj": 8.0},
    ]
    assert _monthly_trend(pts, since=_STD_BAND_END) == [
        {"date": "2024-07-01", "price": 5.0},
        {"date": "2024-08-01", "price": 7.0},
    ]


def test_monthly_trend_needs_two_months():
    pts = [
        {"date": "2024-08-10", "unit_price_adj": 6.0},
        {"date": "2024-08-20", "unit_price_adj": 8.0},
    ]
    assert _monthly_trend(pts, since=_STD_BAND_END) == []


def test_band_constants_are_ordered_iso_dates():
    assert _STD_BAND_START < _STD_BAND_END
    assert _STD_BAND_START.count("-") == 2 and len(_STD_BAND_START) == 10
