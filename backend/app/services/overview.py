"""Overview — the scoped revenue / invoice KPIs, the monthly series, and the
year-over-year annual comparison. Ported from dashboard/views/home.py; the
"needs attention" digest stays in routers/overview.py (it needs a live conn).

Revenue is the product-line basis throughout: sum(qbo_invoice_items.line_total)
where category='product' (the dashboard-redesign invariant). The annual
comparison respects the customer / product / size / sample filters but not the
page date range — a date window would gut a chart whose whole job is comparing
full years."""

from __future__ import annotations

import math

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope
from ._util import finite as _finite
from . import breakdown as _bd
from .context import prepared_frames, slice_by_date
from .lifecycle import matched_gap_summary, month_breakdowns

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_SPARK_MONTHS = 6


def _prev_window(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The period of equal length immediately before [start, end]."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    prev_end = s - pd.Timedelta(days=1)
    prev_start = prev_end - (e - s)
    return prev_start, prev_end


def _delta(curr: float, prev: float | None, *, prefix: str = "", decimals: int = 0) -> tuple[str | None, str | None]:
    if prev is None or pd.isna(prev) or not math.isfinite(_finite(curr, float("nan"))):
        return None, None
    diff = _finite(curr) - float(prev)
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


def _month_index(*frames: pd.DataFrame) -> list[str]:
    """The union of YYYY-MM buckets present across the given frames, ascending —
    so the two 'by month' charts share one x-axis."""
    months: set[str] = set()
    for df in frames:
        d = df.dropna(subset=["effective_date"])
        if not d.empty:
            months |= set(d["effective_date"].dt.to_period("M").astype(str))
    return sorted(months)


def _series_on(index: list[str], df: pd.DataFrame, *, value_col: str, agg: str) -> list[float | None]:
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return [None] * len(index)
    by = d.assign(_m=d["effective_date"].dt.to_period("M").astype(str))
    g = by.groupby("_m")["id"].nunique() if agg == "nunique" else by.groupby("_m")[value_col].sum()
    return [float(g[m]) if m in g.index else None for m in index]


def overview_page(fp: FilterParams) -> PageResponse:
    inv_all, prod_all, _hidden = prepared_frames(fp)
    f_inv, f_prod = slice_by_date(inv_all, prod_all, fp.start, fp.end)

    if f_inv.empty:
        return PageResponse(
            scope=Scope(count=0, noun="invoices", start=fp.start, end=fp.end),
            notes=["No invoice data for the current scope — widen the date range or clear a filter."],
        )

    revenue = _finite(f_prod["line_total"].sum())
    gross = _finite(f_inv["total_amt"].sum())
    other = round(gross - revenue, 2)
    n_invoices = int(f_inv["id"].nunique())
    # product-bearing customers — the /customers list; a service/donation-only
    # account (e.g. a food bank) isn't counted, so the two pages agree.
    n_customers = int(f_prod["customer_name"].nunique())
    aiv = _finite(f_inv["total_amt"].mean()) if n_invoices else 0.0

    # requested (PO) vs shipped (invoice) — the app's core metric
    gap = matched_gap_summary(fp)

    rev_delta = inv_delta = cust_delta = aiv_delta = None
    rev_dir = inv_dir = cust_dir = aiv_dir = None
    delta_label = None
    if fp.start and fp.end:
        p_start, p_end = _prev_window(fp.start, fp.end)
        p_inv, p_prod = slice_by_date(inv_all, prod_all, p_start, p_end)
        if not p_inv.empty:
            rev_delta, rev_dir = _delta(revenue, _finite(p_prod["line_total"].sum()), prefix="$")
            inv_delta, inv_dir = _delta(n_invoices, float(p_inv["id"].nunique()))
            cust_delta, cust_dir = _delta(n_customers, float(p_prod["customer_name"].nunique()))
            aiv_delta, aiv_dir = _delta(aiv, _finite(p_inv["total_amt"].mean()), prefix="$", decimals=2)
            delta_label = f"vs. {p_start.date()} – {p_end.date()}"

    span_note = (
        f"Showing {fp.start} – {fp.end}." if fp.start and fp.end
        else "Showing all time — pick a date range above for period-over-period deltas."
    )
    breakdown = (
        f"Gross invoiced ${gross:,.0f} — product revenue ${revenue:,.0f} (the basis for this "
        f"page) plus ${other:,.0f} of non-product lines: service, delivery, credits / "
        f"donations, and hidden / sample items."
    )

    kpis = [
        Kpi(label="Product revenue", value=round(revenue, 2), format="currency",
            delta=rev_delta, delta_direction=rev_dir, delta_label=delta_label,
            help="Sum of product line items (category='product') on invoices in scope. "
                 "Shipping / services / samples are not counted — see the note below.",
            spark=_trailing(f_prod, value_col="line_total", agg="sum") or None),
        Kpi(label="Under-shipped", value=round(gap.lost, 2), format="currency",
            help="The lost sales: Σ (requested − shipped) over matched order lines invoiced "
                 "for less than the PO asked. Same figure as Order Lifecycle; full breakdown there."),
        Kpi(label="Fulfilment rate", value=gap.fulfil, format="percent",
            help="Σ shipped ÷ Σ requested across matched order lines — matches Order Lifecycle."),
        Kpi(label="Invoices", value=n_invoices, format="int",
            delta=inv_delta, delta_direction=inv_dir, delta_label=delta_label,
            spark=_trailing(f_inv, value_col="id", agg="nunique") or None),
        Kpi(label="Customers", value=n_customers, format="int",
            delta=cust_delta, delta_direction=cust_dir, delta_label=delta_label,
            help="Distinct customers with product revenue in scope — the Customers list."),
        Kpi(label="Avg invoice value", value=round(aiv, 2), format="currency2",
            delta=aiv_delta, delta_direction=aiv_dir, delta_label=delta_label,
            help="Mean of the invoice header total (gross — includes shipping / tax), "
                 "not the product-revenue basis."),
    ]

    gap_ix = _month_index(gap.m) if not gap.m.empty else []
    month_ix = _month_index(f_prod, f_inv)
    inv_counts = _series_on(month_ix, f_inv, value_col="id", agg="nunique")
    # month-over-month change in the invoice count — +ve = more invoices than the
    # prior month, -ve = fewer. First month has no prior, so it's null.
    inv_change = [None] + [
        (inv_counts[i] - inv_counts[i - 1])
        if inv_counts[i] is not None and inv_counts[i - 1] is not None else None
        for i in range(1, len(inv_counts))
    ]
    charts = [
        Chart(id="req_vs_shipped", title="Requested vs shipped by month", kind="line", x=gap_ix,
              width="full",
              series=[
                  ChartSeries(name="Requested",
                              data=_series_on(gap_ix, gap.m, value_col="requested_amount", agg="sum")
                              if not gap.m.empty else []),
                  ChartSeries(name="Shipped",
                              data=_series_on(gap_ix, gap.m, value_col="delivered_amount", agg="sum")
                              if not gap.m.empty else []),
              ], y_format="currency",
              breakdowns=month_breakdowns(gap.m, gap_ix) if not gap.m.empty else None),
        Chart(id="rev_month", title="Product revenue by month", kind="line", x=month_ix,
              series=[ChartSeries(name="Revenue",
                                  data=_series_on(month_ix, f_prod, value_col="line_total", agg="sum"))],
              y_format="currency",
              breakdowns=[
                  _bd.by_month(f_prod, month_ix, group="product_name", value="line_total",
                               label="Top products"),
                  _bd.by_month(f_prod, month_ix, group="customer_name", value="line_total",
                               label="Top customers"),
              ]),
        Chart(id="inv_month", title="Invoices by month", kind="bar", x=month_ix,
              series=[ChartSeries(name="Invoices", data=inv_counts)],
              y_format="int",
              breakdowns=[
                  _bd.by_month(f_inv, month_ix, group="customer_name", value="id", agg="nunique",
                               label="Top customers", fmt="int"),
              ]),
        Chart(id="inv_change", title="Invoice change, month over month", kind="bar", x=month_ix,
              series=[ChartSeries(name="Change vs. prior month", data=inv_change)],
              y_format="int"),
        Chart(id="rev_yoy", title="Revenue by month, year over year", kind="line", x=list(_MONTHS),
              width="full",
              series=_yoy(prod_all, value_col="line_total", agg="sum"), y_format="currency"),
        Chart(id="inv_yoy", title="Invoices by month, year over year", kind="line", x=list(_MONTHS),
              width="full",
              series=_yoy(inv_all, value_col="id", agg="nunique"), y_format="int"),
    ]

    return PageResponse(
        scope=Scope(count=n_invoices, noun="invoices", start=fp.start, end=fp.end, note=span_note),
        kpis=kpis,
        charts=charts,
        notes=[breakdown],
    )
