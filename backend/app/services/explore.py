"""Explore — the slice-and-dice surface. `explore()` is the default PageResponse
(revenue by month / customer / product + MoM movers); `pivot()` is the
measure × grain × break-by configurator and `compare()` the two-period diff,
both ported from dashboard/views/explore.py."""

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
import data as _dash  # shared/data.py, via app.reuse
from . import breakdown as _bd
from .context import build_context, monthly_revenue, prepared_frames, slice_by_date
from ._util import records

_TOP_N = 15

# --- pivot configurator -------------------------------------------------------

_GRAIN_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
_DIM_COL = {"customer": "customer_name", "product": "product_name", "size": "container_size"}
_MEASURE = {
    "revenue": ("line_total", "sum", "Revenue"),
    "orders": ("invoice_id", "nunique", "Orders"),
    "quantity": ("quantity", "sum", "Quantity"),
}
_TOP_SERIES = 12  # colour cap on the pivot chart; the rest roll into "Other"


def _measure_total(df: pd.DataFrame, col: str, agg: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(df[col].nunique() if agg == "nunique" else df[col].sum())


def pivot(fp: FilterParams, measure: str, grain: str, dims: list[str]) -> PageResponse:
    measure = measure if measure in _MEASURE else "revenue"
    grain = grain if grain in _GRAIN_FREQ or grain == "all" else "month"
    dims = [d for d in dims if d in _DIM_COL] or []
    val_col, agg, val_label = _MEASURE[measure]

    ctx = build_context(fp)
    prod = ctx.f_prod
    if prod.empty or val_col not in prod.columns:
        return PageResponse(scope=Scope(count=0, noun="invoices", start=fp.start, end=fp.end))

    detail = prod.dropna(subset=["effective_date"]).copy()
    if detail.empty:
        return PageResponse(scope=Scope(count=0, noun="invoices", start=fp.start, end=fp.end))

    group_cols: list[str] = []
    if grain != "all":
        detail["period"] = detail["effective_date"].dt.to_period(_GRAIN_FREQ[grain]).dt.start_time
        group_cols.append("period")
    dim_cols = [_DIM_COL[d] for d in dims]
    group_cols += dim_cols

    if group_cols:
        grouped = detail.groupby(group_cols, as_index=False).agg(**{val_label: (val_col, agg)})
    else:
        grouped = pd.DataFrame({val_label: [_measure_total(detail, val_col, agg)]})

    if "period" in group_cols:
        grouped = grouped.sort_values("period")
        grouped["period"] = grouped["period"].dt.strftime("%Y-%m-%d")
    elif val_label in grouped.columns:
        grouped = grouped.sort_values(val_label, ascending=False)

    total = _measure_total(detail, val_col, agg)
    charts: list[Chart] = []
    if grain != "all":
        charts.append(_pivot_chart(detail, dim_cols, val_col, agg, val_label, measure))

    cols = [
        TableColumn(key="period", label="Period", kind="date") if "period" in group_cols else None,
        *[TableColumn(key=c, label=c.replace("_", " ").title()) for c in dim_cols],
        TableColumn(key=val_label, label=val_label,
                    kind="currency" if measure == "revenue" else "int"),
    ]
    return PageResponse(
        scope=Scope(count=int(ctx.n_invoices), noun="invoices", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label=f"Total {measure}", value=round(total, 2),
                format="currency" if measure == "revenue" else "int"),
            Kpi(label="Rows in view", value=int(len(grouped)), format="int"),
        ],
        charts=charts,
        tables={
            "pivot": Table(
                title=f"{val_label} by {grain}" + (f" · {', '.join(dims)}" if dims else ""),
                columns=[c for c in cols if c is not None],
                rows=records(grouped.round(2)),
                export_name="explore_pivot",
            )
        },
    )


def _pivot_chart(detail: pd.DataFrame, dim_cols: list[str], val_col: str, agg: str,
                 val_label: str, measure: str) -> Chart:
    """Time series with up to _TOP_SERIES coloured series on the first break-by
    dimension (rest bucketed 'Other'); a single series when there's no dimension."""
    y_format = "currency" if measure == "revenue" else "int"
    color_dim = dim_cols[0] if dim_cols else None

    if color_dim is None:
        g = detail.groupby("period", as_index=False).agg(**{val_label: (val_col, agg)}).sort_values("period")
        x = [d.strftime("%Y-%m-%d") for d in g["period"]]
        return Chart(id="pivot", kind="line", x=x,
                     series=[ChartSeries(name=val_label, data=[float(v) for v in g[val_label]])],
                     y_format=y_format)

    ranked = (
        detail.groupby(color_dim)[val_col].nunique() if agg == "nunique"
        else detail.groupby(color_dim)[val_col].agg(agg)
    )
    keep = set(ranked.abs().nlargest(_TOP_SERIES).index)
    d = detail.assign(_s=detail[color_dim].where(detail[color_dim].isin(keep), "Other"))
    plot = d.groupby(["period", "_s"], as_index=False).agg(**{val_label: (val_col, agg)})
    periods = sorted(plot["period"].unique())
    x = [pd.Timestamp(p).strftime("%Y-%m-%d") for p in periods]
    idx = {p: i for i, p in enumerate(periods)}
    series: list[ChartSeries] = []
    for name, part in plot.groupby("_s"):
        data: list[float | None] = [None] * len(periods)
        for p, v in zip(part["period"], part[val_label]):
            data[idx[p]] = float(v)
        series.append(ChartSeries(name=str(name), data=data))
    return Chart(id="pivot", kind="line", x=x, series=series, y_format=y_format)


# --- compare two periods ----------------------------------------------------

def compare(fp: FilterParams, a_start: str, a_end: str, b_start: str, b_end: str) -> PageResponse:
    inv_all, prod_all, _hidden = prepared_frames(fp)
    inv_a, prod_a = slice_by_date(inv_all, prod_all, a_start, a_end)
    inv_b, prod_b = slice_by_date(inv_all, prod_all, b_start, b_end)

    n_a, n_b = int(inv_a["id"].nunique()), int(inv_b["id"].nunique())
    rev_a = float(prod_a["line_total"].sum())
    rev_b = float(prod_b["line_total"].sum())

    def _delta(cur: float, prev: float, money: bool) -> str:
        d = cur - prev
        return f"{'$' if money else ''}{d:+,.0f}"

    # compare_periods_by_group uses an inclusive <= on the end bound; invoice
    # effective_dates are date-level so a midnight Timestamp is the right edge.
    movers = _dash.compare_periods_by_group(
        prod_all, "effective_date", "customer_name", "line_total",
        (pd.Timestamp(a_start), pd.Timestamp(a_end)),
        (pd.Timestamp(b_start), pd.Timestamp(b_end)),
    )
    tables: dict[str, Table] = {}
    if movers is not None and not movers.empty:
        tables["movers"] = Table(
            title="Customers with the biggest revenue change, A → B",
            columns=[
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="period_a", label="Period A", kind="currency"),
                TableColumn(key="period_b", label="Period B", kind="currency"),
                TableColumn(key="delta", label="Change", kind="currency"),
            ],
            rows=records(movers.round(2)),
            export_name="period_compare",
        )

    return PageResponse(
        scope=Scope(count=n_a + n_b, noun="invoices", start=a_start, end=b_end,
                    note=f"A {a_start}–{a_end}  ·  B {b_start}–{b_end}"),
        kpis=[
            Kpi(label="Invoices — A", value=n_a, format="int"),
            Kpi(label="Invoices — B", value=n_b, format="int", delta=_delta(n_b, n_a, False),
                delta_direction="up" if n_b > n_a else "down" if n_b < n_a else "flat"),
            Kpi(label="Revenue — A", value=round(rev_a, 2), format="currency"),
            Kpi(label="Revenue — B", value=round(rev_b, 2), format="currency",
                delta=_delta(rev_b, rev_a, True),
                delta_direction="up" if rev_b > rev_a else "down" if rev_b < rev_a else "flat"),
        ],
        tables=tables,
    )


def explore(fp: FilterParams) -> PageResponse:
    ctx = build_context(fp)
    prod = ctx.f_prod
    if prod.empty:
        return PageResponse(scope=Scope(count=0, noun="POs", start=fp.start, end=fp.end))

    months, rev_series = monthly_revenue(prod)
    by_cust = (
        prod.groupby("customer_name")["line_total"].sum().sort_values(ascending=False).head(_TOP_N)
    )
    by_prod = (
        prod.groupby("product_name")["line_total"].sum().sort_values(ascending=False).head(_TOP_N)
    )

    cust_names, prod_names = list(by_cust.index), list(by_prod.index)
    charts = [
        Chart(id="rev_month", title="Product revenue by month", kind="line", x=months,
              series=[ChartSeries(name="Revenue", data=rev_series)], y_format="currency",
              breakdowns=[
                  _bd.by_month(prod, months, group="product_name", value="line_total",
                               label="Top products"),
                  _bd.by_month(prod, months, group="customer_name", value="line_total",
                               label="Top customers"),
              ]),
        Chart(id="rev_customer", title=f"Revenue by customer (top {_TOP_N})", kind="hbar",
              x=cust_names, series=[ChartSeries(name="Revenue", data=[float(v) for v in by_cust.values])],
              y_format="currency",
              breakdowns=[
                  _bd.by_category(prod, cust_names, key="customer_name", group="product_name",
                                  value="line_total", label="Top products"),
              ]),
        Chart(id="rev_product", title=f"Revenue by product (top {_TOP_N})", kind="hbar",
              x=prod_names, series=[ChartSeries(name="Revenue", data=[float(v) for v in by_prod.values])],
              y_format="currency",
              breakdowns=[
                  _bd.by_category(prod, prod_names, key="product_name", group="customer_name",
                                  value="line_total", label="Top customers"),
              ]),
    ]

    tables: dict[str, Table] = {}
    mom = _dash.month_over_month_movers(prod, "effective_date", "customer_name", "line_total")
    if mom is not None:
        merged, curr_m, prev_m, skipped = mom
        # merged cols: customer_name, prev, curr, delta, Change (drop the pre-formatted Change)
        rows = records(merged.drop(columns=[c for c in ("Change",) if c in merged.columns]).round(2))
        note = f"{prev_m} → {curr_m}" + (" (current partial month skipped)" if skipped else "")
        tables["movers"] = Table(
            title=f"Biggest movers by customer · {note}",
            columns=[
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="prev", label="Previous", kind="currency"),
                TableColumn(key="curr", label="Current", kind="currency"),
                TableColumn(key="delta", label="Change", kind="currency"),
            ],
            rows=rows,
            export_name="movers",
        )

    return PageResponse(
        scope=Scope(count=int(ctx.n_invoices), noun="invoices", start=fp.start, end=fp.end),
        charts=charts,
        tables=tables,
    )
