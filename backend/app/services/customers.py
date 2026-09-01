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


def _by_month(df: pd.DataFrame, *, value_col: str | None, agg: str) -> tuple[list[str], list[float]]:
    """(month labels, values) for a per-month sum or distinct-invoice count."""
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return [], []
    m = d.assign(_m=d["effective_date"].dt.to_period("M").astype(str))
    g = (m.groupby("_m")["id"].nunique() if agg == "nunique"
         else m.groupby("_m")[value_col].sum()).sort_index()
    return list(g.index), [finite(v) for v in g.values]


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


def _date_str(ts) -> str:
    return ts.date().isoformat() if ts is not None and pd.notna(ts) else "—"


def customer_detail(fp: FilterParams, name: str) -> PageResponse:
    """One account's dossier: revenue, ordering cadence, and product / size mix,
    scoped to the FilterBar's date range (the customer is the route, not a filter)."""
    ctx = build_context(fp)
    c_prod = ctx.f_prod[ctx.f_prod["customer_name"] == name]
    c_inv = ctx.f_inv[ctx.f_inv["customer_name"] == name]

    if c_prod.empty and c_inv.empty:
        return PageResponse(
            scope=Scope(count=0, noun="orders", start=fp.start, end=fp.end),
            notes=[f"No activity for {name} in this scope — widen the date range, or the "
                   "account may be hidden in Settings → Visibility."],
        )

    revenue = finite(c_prod["line_total"].sum())
    n_orders = int(c_inv["id"].nunique())
    prod_orders = int(c_prod["invoice_id"].nunique())
    aov = round(revenue / prod_orders, 2) if prod_orders else 0.0
    first = c_inv["effective_date"].min() if not c_inv.empty else None
    last = c_inv["effective_date"].max() if not c_inv.empty else None

    rev_m, rev_v = _by_month(c_prod, value_col="line_total", agg="sum")
    ord_m, ord_v = _by_month(c_inv, value_col=None, agg="nunique")

    by_product = (
        c_prod.groupby("product_name")["line_total"].sum()
        .sort_values(ascending=False).head(_TOP_N)
    )
    by_size = (
        c_prod.groupby("container_size")["quantity"].sum()
        .sort_values(ascending=False)
    )

    pb = (
        c_prod.groupby(["product_name", "container_size"])
        .agg(orders=("invoice_id", "nunique"), qty=("quantity", "sum"),
             revenue=("line_total", "sum"), last_ordered=("effective_date", "max"))
        .reset_index()
    )
    pb["avg_price"] = (pb["revenue"] / pb["qty"].where(pb["qty"] > 0)).round(2)
    pb["last_ordered"] = pd.to_datetime(pb["last_ordered"]).dt.date.astype("object")
    pb = pb.sort_values("revenue", ascending=False)

    return PageResponse(
        scope=Scope(count=n_orders, noun="orders", start=fp.start, end=fp.end,
                    note=(f"{_date_str(first)} – {_date_str(last)}" if first is not None else None)),
        kpis=[
            Kpi(label="Product revenue", value=revenue, format="currency",
                help="Sum of product line items; shipping / services / samples excluded."),
            Kpi(label="Orders", value=n_orders, format="int",
                help="Distinct invoices in scope."),
            Kpi(label="Avg order value", value=aov, format="currency",
                help="Product revenue ÷ invoices carrying a product line."),
            Kpi(label="First order", value=_date_str(first), format="text"),
            Kpi(label="Last order", value=_date_str(last), format="text"),
        ],
        charts=[
            Chart(id="rev_month", title="Product revenue by month", kind="line",
                  x=rev_m, series=[ChartSeries(name="Revenue", data=rev_v)], y_format="currency"),
            Chart(id="orders_month", title="Orders by month", kind="bar",
                  x=ord_m, series=[ChartSeries(name="Orders", data=ord_v)], y_format="int"),
            Chart(id="rev_by_product", title=f"Revenue by product (top {_TOP_N})", kind="hbar",
                  x=list(by_product.index),
                  series=[ChartSeries(name="Revenue", data=[finite(v) for v in by_product.values])],
                  y_format="currency"),
            Chart(id="qty_by_size", title="Quantity by container size", kind="bar",
                  x=list(by_size.index),
                  series=[ChartSeries(name="Units", data=[finite(v) for v in by_size.values])],
                  y_format="int"),
        ],
        tables={
            "products": Table(
                title=f"Products bought ({pb.shape[0]})",
                columns=[
                    TableColumn(key="product_name", label="Product"),
                    TableColumn(key="container_size", label="Size"),
                    TableColumn(key="orders", label="Orders", kind="int"),
                    TableColumn(key="qty", label="Units", kind="int"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="avg_price", label="Avg unit price", kind="currency2"),
                    TableColumn(key="last_ordered", label="Last ordered", kind="date"),
                ],
                rows=records(pb.head(_ROW_CAP)[["product_name", "container_size", "orders",
                                               "qty", "revenue", "avg_price", "last_ordered"]]),
                export_name=f"{name}_products",
            )
        },
    )
