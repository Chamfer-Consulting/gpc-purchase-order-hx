"""Explore — revenue cut by month / customer / product, plus month-over-month
movers. A first cut of dashboard/views/explore.py; the full pivot configurator
(measure × dimension × grain, compare-two-periods) needs extra query params and
lands later."""

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, PageResponse, Scope, Table, TableColumn
import data as _dash  # dashboard/data.py, via app.reuse
from .context import build_context, monthly_revenue
from ._util import records

_TOP_N = 15


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

    charts = [
        Chart(id="rev_month", title="Product revenue by month", kind="line", x=months,
              series=[ChartSeries(name="Revenue", data=rev_series)], y_format="currency"),
        Chart(id="rev_customer", title=f"Revenue by customer (top {_TOP_N})", kind="hbar",
              x=list(by_cust.index), series=[ChartSeries(name="Revenue", data=[float(v) for v in by_cust.values])],
              y_format="currency"),
        Chart(id="rev_product", title=f"Revenue by product (top {_TOP_N})", kind="hbar",
              x=list(by_prod.index), series=[ChartSeries(name="Revenue", data=[float(v) for v in by_prod.values])],
              y_format="currency"),
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
