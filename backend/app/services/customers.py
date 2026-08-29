"""Customer 360 — revenue, orders, average order value per customer, on the
product-revenue basis. Ported from dashboard/views/customer_360.py."""

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from .context import build_context, monthly_revenue
from ._util import records

_TOP_N = 15


def customer_360(fp: FilterParams) -> PageResponse:
    ctx = build_context(fp)
    prod = ctx.f_prod

    if prod.empty:
        return PageResponse(scope=Scope(count=0, noun="customers", start=fp.start, end=fp.end))

    g = (
        prod.groupby("customer_name")
        .agg(revenue=("line_total", "sum"), orders=("invoice_id", "nunique"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    g["avg_order"] = (g["revenue"] / g["orders"].replace(0, 1)).round(2)

    total_rev = float(g["revenue"].sum())
    total_orders = int(g["orders"].sum())

    months, series = monthly_revenue(prod)
    top = g.head(_TOP_N)

    return PageResponse(
        scope=Scope(count=int(g.shape[0]), noun="customers", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label="Product revenue", value=total_rev, format="currency"),
            Kpi(label="Customers", value=int(g.shape[0]), format="int"),
            Kpi(label="Orders", value=total_orders, format="int"),
            Kpi(label="Avg order value", value=round(total_rev / max(total_orders, 1), 2), format="currency"),
        ],
        charts=[
            Chart(
                id="rev_by_customer",
                title=f"Revenue by customer (top {_TOP_N})",
                kind="hbar",
                x=list(top["customer_name"]),
                series=[ChartSeries(name="Revenue", data=[float(v) for v in top["revenue"]])],
                y_format="currency",
            ),
            Chart(
                id="rev_by_month",
                title="Product revenue by month",
                kind="line",
                x=months,
                series=[ChartSeries(name="Revenue", data=series)],
                y_format="currency",
            ),
        ],
        tables={
            "customers": Table(
                title="All customers in scope",
                columns=[
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="orders", label="Orders", kind="int"),
                    TableColumn(key="avg_order", label="Avg order", kind="currency2"),
                ],
                rows=records(g),
                export_name="customers",
            )
        },
    )
