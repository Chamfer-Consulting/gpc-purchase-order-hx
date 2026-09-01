"""Chart tooltip breakdowns — the top constituents (products / customers / sizes)
behind each point of a chart, so a hover answers "which items / accounts drove
this?". Attached to a Chart via `breakdowns=[...]`; the SPA renders them under the
series values in the tooltip.

Two shapes:
  * `by_month` — for the "… by month" line / bar charts (x is YYYY-MM).
  * `by_category` — for "top N by …" hbar charts (x is the bar's own label);
    the breakdown is the *other* dimension (hover a customer → its top products).
"""

from __future__ import annotations

import pandas as pd

from ..schemas import BreakdownPoint, BreakdownRow, ChartBreakdown, NumFormat

TOP_N = 5

_PRETTY = {"product_name": "product", "customer_name": "customer",
           "container_size": "size", "size_label": "size"}


def _by(col: str) -> str:
    return _PRETTY.get(col, col.replace("_name", "").replace("_label", ""))


def _rows(series: pd.Series, top_n: int) -> list[BreakdownRow]:
    s = series[series != 0].sort_values(ascending=False).head(top_n)
    return [BreakdownRow(name=str(k), value=round(float(v), 2)) for k, v in s.items()]


def by_month(
    df: pd.DataFrame,
    months: list[str],
    *,
    group: str,
    value: str,
    label: str,
    agg: str = "sum",
    fmt: NumFormat = "currency",
    top_n: int = TOP_N,
) -> ChartBreakdown:
    """Per YYYY-MM in `months`, the top `group` values by `agg` of `value`."""
    empty = [BreakdownPoint(x=m, rows=[]) for m in months]
    d = df.dropna(subset=["effective_date"]) if "effective_date" in df.columns else df.iloc[0:0]
    if d.empty or group not in d.columns or value not in d.columns:
        return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=empty)
    d = d.assign(
        _m=d["effective_date"].dt.to_period("M").astype(str),
        _g=d[group].fillna("—").replace("", "—"),
    )
    grouped = d.groupby(["_m", "_g"])[value]
    g = grouped.nunique() if agg == "nunique" else grouped.sum()
    lvl0 = set(g.index.get_level_values(0))
    pts = [
        BreakdownPoint(x=m, rows=_rows(g.loc[m], top_n) if m in lvl0 else [])
        for m in months
    ]
    return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=pts)


def by_category(
    df: pd.DataFrame,
    categories: list,
    *,
    key: str,
    group: str,
    value: str,
    label: str,
    agg: str = "sum",
    fmt: NumFormat = "currency",
    top_n: int = TOP_N,
) -> ChartBreakdown:
    """Per bar label in `categories` (a value of `key`), the top `group` values —
    the cross-dimension for an hbar."""
    empty = [BreakdownPoint(x=str(c), rows=[]) for c in categories]
    if df.empty or key not in df.columns or group not in df.columns or value not in df.columns:
        return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=empty)
    d = df.assign(
        _k=df[key].fillna("—").replace("", "—"),
        _g=df[group].fillna("—").replace("", "—"),
    )
    grouped = d.groupby(["_k", "_g"])[value]
    g = grouped.nunique() if agg == "nunique" else grouped.sum()
    lvl0 = set(g.index.get_level_values(0))
    pts = [
        BreakdownPoint(x=str(c), rows=_rows(g.loc[str(c)], top_n) if str(c) in lvl0 else [])
        for c in categories
    ]
    return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=pts)
