"""Customers — the account portfolio: revenue, orders, average order value and
recency per customer, on the product-revenue basis. Ported from
dashboard/views/customer_360.py (which was a per-customer dossier; this is the
list view — hidden customers follow Settings → Visibility, see context.py)."""

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from ._util import finite, records
from .context import build_context, monthly_revenue

_TOP_N = 15
_ROW_CAP = 300


def customer_360(fp: FilterParams) -> PageResponse:
    ctx = build_context(fp)
    prod, inv = ctx.f_prod, ctx.f_inv

    if prod.empty:
        return PageResponse(
            scope=Scope(count=0, noun="customers", start=fp.start, end=fp.end),
            notes=["No customer data for this scope — widen the date range or clear a filter. "
                   "Deleted / archived accounts are hidden via Settings → Visibility."],
        )

    # revenue + product-order count from the product lines; the true order count and
    # first/last activity from the invoice frame (a customer can have service-only
    # invoices that carry no product line).
    rev = (
        prod.groupby("customer_name")
        .agg(revenue=("line_total", "sum"), prod_orders=("invoice_id", "nunique"))
        .reset_index()
    )
    inv_g = (
        inv.groupby("customer_name")
        .agg(orders=("id", "nunique"),
             first_order=("effective_date", "min"),
             last_order=("effective_date", "max"))
        .reset_index()
    )
    g = rev.merge(inv_g, on="customer_name", how="left")
    g["orders"] = g["orders"].fillna(g["prod_orders"]).astype(int)
    g["avg_order"] = (g["revenue"] / g["prod_orders"].where(g["prod_orders"] > 0)).round(2)
    for c in ("first_order", "last_order"):
        g[c] = pd.to_datetime(g[c]).dt.date.astype("object")
    g = g.sort_values("revenue", ascending=False)

    total_rev = finite(g["revenue"].sum())
    total_orders = int(g["orders"].sum())
    n_customers = int(g.shape[0])
    aov = round(total_rev / total_orders, 2) if total_orders else 0.0

    months, series = monthly_revenue(prod)
    top = g.head(_TOP_N)
    shown = g.head(_ROW_CAP)
    title = "All customers in scope"
    if n_customers > _ROW_CAP:
        title = f"Customers in scope ({n_customers}) — showing {_ROW_CAP}"
    else:
        title = f"Customers in scope ({n_customers})"

    return PageResponse(
        scope=Scope(count=n_customers, noun="customers", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label="Product revenue", value=total_rev, format="currency",
                help="Sum of product line items (category='product'); shipping / services "
                     "/ samples are not counted."),
            Kpi(label="Customers", value=n_customers, format="int"),
            Kpi(label="Orders", value=total_orders, format="int",
                help="Distinct invoices in scope. A customer's average below divides "
                     "revenue by only the invoices that carry a product line."),
            Kpi(label="Avg order value", value=aov, format="currency",
                help="Product revenue ÷ orders with a product line."),
        ],
        charts=[
            Chart(
                id="rev_by_customer",
                title=f"Revenue by customer (top {_TOP_N})",
                kind="hbar",
                x=list(top["customer_name"]),
                series=[ChartSeries(name="Revenue", data=[finite(v) for v in top["revenue"]])],
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
                title=title,
                columns=[
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="orders", label="Orders", kind="int"),
                    TableColumn(key="avg_order", label="Avg order", kind="currency"),
                    TableColumn(key="first_order", label="First order", kind="date"),
                    TableColumn(key="last_order", label="Last order", kind="date"),
                ],
                rows=records(shown[["customer_name", "revenue", "orders", "avg_order",
                                    "first_order", "last_order"]]),
                export_name="customers",
            )
        },
    )
