"""Overview — the scoped revenue / invoice KPIs, the monthly series, and the
year-over-year annual comparison. Ported from dashboard/views/home.py; the
"needs attention" digest stays in routers/overview.py (it needs a live conn).

Revenue is the product-line basis throughout: sum(qbo_invoice_items.line_total)
where category='product' (the dashboard-redesign invariant). The annual
comparison respects the customer / product / size / sample filters but not the
page date range — a date window would gut a chart whose whole job is comparing
full years."""

from __future__ import annotations

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope
from .context import monthly_revenue, prepared_frames, slice_by_date

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_SPARK_MONTHS = 6


def _prev_window(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The period of equal length immediately before [start, end]."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    prev_end = s - pd.Timedelta(days=1)
    prev_start = prev_end - (e - s)
    return prev_start, prev_end


def _delta(curr: float, prev: float | None, *, prefix: str = "", decimals: int = 0) -> tuple[str | None, str | None]:
    if prev is None or pd.isna(prev):
        return None, None
    diff = curr - prev
    direction = "up" if diff > 0 else "down" if diff < 0 else "flat"
    return f"{prefix}{diff:+,.{decimals}f}", direction


def _trailing(df: pd.DataFrame, *, value_col: str, agg: str) -> list[float]:
    """Last _SPARK_MONTHS months of a metric, oldest first. [] if < 2 points."""
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return []
    m = d.assign(_m=d["effective_date"].dt.to_period("M"))
    series = m.groupby("_m")["id"].nunique() if agg == "nunique" else m.groupby("_m")[value_col].sum()
    series = series.sort_index().tail(_SPARK_MONTHS)
    return [float(v) for v in series] if len(series) >= 2 else []


def _monthly_invoice_counts(inv: pd.DataFrame) -> tuple[list[str], list[float]]:
    d = inv.dropna(subset=["effective_date"])
    if d.empty:
        return [], []
    g = d.assign(_m=d["effective_date"].dt.to_period("M").astype(str)).groupby("_m")["id"].nunique().sort_index()
    return list(g.index), [float(v) for v in g.values]


def _yoy(df: pd.DataFrame, *, value_col: str, agg: str) -> list[ChartSeries]:
    """One series per calendar year, 12 points (Jan..Dec), None where a month has
    no data. Years ascending so the current year draws last."""
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return []
    d = d.assign(_y=d["effective_date"].dt.year, _moy=d["effective_date"].dt.month)
    grouped = (
        d.groupby(["_y", "_moy"])["id"].nunique() if agg == "nunique"
        else d.groupby(["_y", "_moy"])[value_col].sum()
    )
    out: list[ChartSeries] = []
    for year in sorted(d["_y"].unique()):
        by_moy = grouped.loc[year] if year in grouped.index.get_level_values(0) else pd.Series(dtype=float)
        out.append(ChartSeries(
            name=str(int(year)),
            data=[float(by_moy[m]) if m in by_moy.index else None for m in range(1, 13)],
        ))
    return out


def overview_page(fp: FilterParams) -> PageResponse:
    inv_all, prod_all, _hidden = prepared_frames(fp)
    f_inv, f_prod = slice_by_date(inv_all, prod_all, fp.start, fp.end)

    if f_inv.empty:
        return PageResponse(scope=Scope(count=0, noun="invoices", start=fp.start, end=fp.end))

    revenue = float(f_prod["line_total"].sum())
    n_invoices = int(f_inv["id"].nunique())
    n_customers = int(f_inv["customer_name"].nunique())
    n_products = int(f_prod["product_name"].nunique())
    aiv = float(f_inv["total_amt"].mean()) if n_invoices else 0.0

    rev_delta = inv_delta = aiv_delta = None
    rev_dir = inv_dir = aiv_dir = None
    note = None
    if fp.start and fp.end:
        p_start, p_end = _prev_window(fp.start, fp.end)
        p_inv, p_prod = slice_by_date(inv_all, prod_all, p_start, p_end)
        if not p_inv.empty:
            rev_delta, rev_dir = _delta(revenue, float(p_prod["line_total"].sum()), prefix="$")
            inv_delta, inv_dir = _delta(n_invoices, float(p_inv["id"].nunique()))
            aiv_delta, aiv_dir = _delta(aiv, float(p_inv["total_amt"].mean()), prefix="$", decimals=2)
            note = (
                f"Deltas vs. {p_start.date()} – {p_end.date()} (the preceding "
                f"{(p_end - p_start).days + 1} days)."
            )

    kpis = [
        Kpi(label="Product revenue", value=round(revenue, 2), format="currency",
            delta=rev_delta, delta_direction=rev_dir,
            spark=_trailing(f_prod, value_col="line_total", agg="sum") or None),
        Kpi(label="Invoices", value=n_invoices, format="int",
            delta=inv_delta, delta_direction=inv_dir,
            spark=_trailing(f_inv, value_col="id", agg="nunique") or None),
        Kpi(label="Customers", value=n_customers, format="int"),
        Kpi(label="Products", value=n_products, format="int"),
        Kpi(label="Avg invoice value", value=round(aiv, 2), format="currency2",
            delta=aiv_delta, delta_direction=aiv_dir),
    ]

    months, rev_series = monthly_revenue(f_prod)
    inv_months, inv_counts = _monthly_invoice_counts(f_inv)
    charts = [
        Chart(id="rev_month", title="Product revenue by month", kind="line", x=months,
              series=[ChartSeries(name="Revenue", data=rev_series)], y_format="currency"),
        Chart(id="inv_month", title="Invoices by month", kind="bar", x=inv_months,
              series=[ChartSeries(name="Invoices", data=inv_counts)], y_format="int"),
        Chart(id="rev_yoy", title="Revenue by month, year over year", kind="line", x=list(_MONTHS),
              series=_yoy(prod_all, value_col="line_total", agg="sum"), y_format="currency"),
        Chart(id="inv_yoy", title="Invoices by month, year over year", kind="line", x=list(_MONTHS),
              series=_yoy(inv_all, value_col="id", agg="nunique"), y_format="int"),
    ]

    return PageResponse(
        scope=Scope(count=n_invoices, noun="invoices", start=fp.start, end=fp.end, note=note),
        kpis=kpis,
        charts=charts,
    )
