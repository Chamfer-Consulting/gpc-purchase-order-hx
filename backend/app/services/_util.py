"""Shared service helpers."""

import pandas as pd


def records(df: pd.DataFrame) -> list[dict]:
    """df.to_dict('records') with NaN/NaT -> None. Raw NaN is invalid JSON and
    FastAPI's encoder emits a bare `NaN` token that browsers reject."""
    if df.empty:
        return []
    clean = df.astype(object).where(pd.notna(df), None)
    return clean.to_dict("records")
