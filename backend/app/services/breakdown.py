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

from collections import defaultdict

import pandas as pd

from ..schemas import BreakdownPoint, BreakdownRow, ChartBreakdown, NumFormat

TOP_N = 5

_PRETTY = {"product_name": "product", "customer_name": "customer",
           "customer_canonical": "customer", "container_size": "size", "size_label": "size"}


def _by(col: str) -> str:
    return _PRETTY.get(col, col.replace("_name", "").replace("_label", ""))


def _bucketed(g: pd.Series) -> dict[str, list[tuple[str, float]]]:
    """A 2-level (bucket, group) Series → {bucket: [(group, value), …]}. Iterating
    the Series directly sidesteps `.loc[bucket]` collapsing to a scalar when a
    bucket has a single group."""
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for key, val in g.items():
        bucket, group = key
        out[str(bucket)].append((str(group), float(val)))
    return out


def _rows(pairs: list[tuple[str, float]], top_n: int) -> list[BreakdownRow]:
    ranked = sorted((p for p in pairs if p[1] != 0), key=lambda p: p[1], reverse=True)
    return [BreakdownRow(name=n, value=round(v, 2)) for n, v in ranked[:top_n]]


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
    buckets = _bucketed(g)
    pts = [BreakdownPoint(x=m, rows=_rows(buckets.get(m, []), top_n)) for m in months]
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
    cats = [str(c) for c in categories]
    empty = [BreakdownPoint(x=c, rows=[]) for c in cats]
    if df.empty or key not in df.columns or group not in df.columns or value not in df.columns:
        return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=empty)
    d = df.assign(
        _k=df[key].fillna("—").replace("", "—").astype(str),
        _g=df[group].fillna("—").replace("", "—"),
    )
    grouped = d.groupby(["_k", "_g"])[value]
    g = grouped.nunique() if agg == "nunique" else grouped.sum()
    buckets = _bucketed(g)
    pts = [BreakdownPoint(x=c, rows=_rows(buckets.get(c, []), top_n)) for c in cats]
    return ChartBreakdown(by=_by(group), label=label, value_format=fmt, points=pts)
