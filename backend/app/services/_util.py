"""Shared service helpers."""

import math

import pandas as pd


def records(df: pd.DataFrame) -> list[dict]:
    """df.to_dict('records') with NaN/NaT -> None. Raw NaN is invalid JSON and
    FastAPI's encoder emits a bare `NaN` token that browsers reject."""
    if df.empty:
        return []
    clean = df.astype(object).where(pd.notna(df), None)
    return clean.to_dict("records")


def finite(x, default: float = 0.0) -> float:
    """A JSON-safe float. NaN/inf (e.g. .mean() of an all-null column) serialise as
    the bare token `NaN`, which the browser's response.json() then rejects, blanking
    the whole page."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default
