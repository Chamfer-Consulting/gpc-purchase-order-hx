"""Customers — the account portfolio: revenue, orders, average order value and
recency per customer, on the product-revenue basis. The list view; a per-customer
dossier lives at /customers/:name (customer_detail). Hidden / archived accounts
follow Settings → Visibility (see context.py)."""

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from . import breakdown as _bd
from ._util import finite, records
from .context import build_context, monthly_revenue
from .lifecycle import matched_gap_summary

_TOP_N = 15
_ROW_CAP = 300


def _gap_frame(fp: FilterParams) -> pd.DataFrame:
    """Matched PO⇄invoice lines with priced-only under/over/requested/delivered
    columns and a `cust` key = the linked QBO customer (data.customer_canonical),
    so the many PO-side spellings roll up to one real account."""
    gm = matched_gap_summary(fp).m
    if gm.empty:
        return pd.DataFrame(columns=["cust", "u", "o", "gr", "gd"])
    key = "customer_canonical" if "customer_canonical" in gm.columns else "customer_name"
    priced = gm["requested_amount"] > 0
    return pd.DataFrame({
        "cust": gm[key].fillna(gm["customer_name"]).astype(str),
        "u": gm["lost_amount"].where(priced, 0.0),
        "o": gm["over_amount"].where(priced, 0.0),
        "gr": gm["requested_amount"].where(priced, 0.0),
        "gd": gm["delivered_amount"].where(priced, 0.0),
    })


def _gap_by_customer(fp: FilterParams) -> dict:
    """{QBO customer -> (under, over, greq, gdel)} — an exact join key now that the
    frame carries the linked invoice's customer, so no fuzzy re-attribution."""
    gf = _gap_frame(fp)
    if gf.empty:
        return {}
    agg = gf.groupby("cust").agg(u=("u", "sum"), o=("o", "sum"), gr=("gr", "sum"), gd=("gd", "sum"))
    return {str(k): tuple(v) for k, v in agg.iterrows()}


def _row_gap(vals: tuple | None) -> tuple[float, float, float | None]:
    """(under $, over $, fulfilment %) for a gap bucket; % is shipped ÷ requested
    over priced lines (>100 ⇒ net over-delivered), None when no matched priced lines."""
    if not vals:
        return 0.0, 0.0, None
    under, over, greq, gdel = vals
    return round(under, 2), round(over, 2), (round(gdel / greq * 100, 1) if greq else None)


def _by_month(df: pd.DataFrame, *, value_col: str | None, agg: str) -> tuple[list[str], list[float]]:
    """(month labels, values) for a per-month sum or distinct-invoice count."""
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return [], []
    m = d.assign(_m=d["effective_date"].dt.to_period("M").astype(str))
    g = (m.groupby("_m")["id"].nunique() if agg == "nunique"
         else m.groupby("_m")[value_col].sum()).sort_index()
    return list(g.index), [finite(v) for v in g.values]


def customers_page(fp: FilterParams) -> PageResponse:
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

    # requested (PO) vs shipped (invoice) per customer — see Order Lifecycle. The
    # gap frame keys on the linked QBO customer, so this is an exact join.
    gap = _gap_by_customer(fp)
    g[["under_shipped", "over_shipped", "fulfil_pct"]] = [
        _row_gap(gap.get(n)) for n in g["customer_name"]
    ]
    g = g.sort_values("revenue", ascending=False)

    total_rev = finite(g["revenue"].sum())
    total_orders = int(g["orders"].sum())
    total_prod_orders = int(g["prod_orders"].sum())
    n_customers = int(g.shape[0])
    aov = round(total_rev / total_prod_orders, 2) if total_prod_orders else 0.0
    total_under = round(finite(g["under_shipped"].sum()), 2)
    total_over = round(finite(g["over_shipped"].sum()), 2)

    # gap tied to accounts not shown here (hidden / archived) — kept out of the totals
    _visible = set(g["customer_name"])
    unattr_u = sum(v[0] for k, v in gap.items() if k not in _visible)
    unattr_o = sum(v[1] for k, v in gap.items() if k not in _visible)

    months, series = monthly_revenue(prod)
    top = g.head(_TOP_N)
    shown = g.head(_ROW_CAP)
    if n_customers > _ROW_CAP:
        title = f"Customers in scope ({n_customers}) — showing {_ROW_CAP}"
    else:
        title = f"Customers in scope ({n_customers})"

    notes = []
    if round(unattr_u, 2) or round(unattr_o, 2):
        notes.append(
            f"${unattr_u:,.0f} under- / ${unattr_o:,.0f} over-shipped is tied to accounts not "
            "listed here (hidden or archived in Settings → Visibility) and isn't in the totals "
            "above — see Order Lifecycle for the portfolio-wide figure."
        )

    return PageResponse(
        scope=Scope(count=n_customers, noun="customers", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label="Product revenue", value=total_rev, format="currency",
                help="Sum of product line items (category='product'); shipping / services "
                     "/ samples are not counted."),
            Kpi(label="Under-shipped", value=total_under, format="currency",
                help="Σ (requested − shipped) across matched PO⇄invoice lines invoiced for "
                     "less than the PO asked. Per customer in the table; detail on Order Lifecycle."),
            Kpi(label="Over-shipped", value=total_over, format="currency",
                help="Σ (shipped − requested) on lines invoiced for more than the PO asked."),
            Kpi(label="Orders", value=total_orders, format="int",
                help="Distinct invoices in scope (including service-only invoices)."),
            Kpi(label="Avg order value", value=aov, format="currency",
                help="Product revenue ÷ invoices carrying a product line (the basis of the "
                     "table's Avg order column)."),
        ],
        charts=[
            Chart(
                id="rev_by_customer",
                title=f"Revenue by customer (top {_TOP_N})",
                kind="hbar",
                x=list(top["customer_name"]),
                series=[ChartSeries(name="Revenue", data=[finite(v) for v in top["revenue"]])],
                y_format="currency",
                breakdowns=[
                    _bd.by_category(prod, list(top["customer_name"]), key="customer_name",
                                    group="product_name", value="line_total", label="Top products"),
                ],
            ),
            Chart(
                id="rev_by_month",
                title="Product revenue by month",
                kind="line",
                x=months,
                series=[ChartSeries(name="Revenue", data=series)],
                y_format="currency",
                breakdowns=[
                    _bd.by_month(prod, months, group="product_name", value="line_total",
                                 label="Top products"),
                    _bd.by_month(prod, months, group="customer_name", value="line_total",
                                 label="Top customers"),
                ],
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
                    TableColumn(key="under_shipped", label="Under-shipped $", kind="currency"),
                    TableColumn(key="over_shipped", label="Over-shipped $", kind="currency"),
                    TableColumn(key="fulfil_pct", label="Fulfilment %", kind="percent"),
                    TableColumn(key="first_order", label="First order", kind="date"),
                    TableColumn(key="last_order", label="Last order", kind="date"),
                ],
                rows=records(shown[["customer_name", "revenue", "orders", "avg_order",
                                    "under_shipped", "over_shipped", "fulfil_pct",
                                    "first_order", "last_order"]]),
                export_name="customers",
            )
        },
        notes=notes,
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

    # gap for just this account — exact match on the linked QBO customer
    gf = _gap_frame(fp)
    gf = gf[gf["cust"] == name]
    if gf.empty:
        under, over, fulfil = 0.0, 0.0, None
    else:
        gr = float(gf["gr"].sum())
        under = round(float(gf["u"].sum()), 2)
        over = round(float(gf["o"].sum()), 2)
        fulfil = round(float(gf["gd"].sum()) / gr * 100, 1) if gr else None

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
            Kpi(label="Under-shipped", value=under, format="currency",
                help="Σ (requested − shipped) on this account's matched PO⇄invoice lines "
                     "invoiced for less than the PO asked."),
            Kpi(label="Over-shipped", value=over, format="currency",
                help="Σ (shipped − requested) on lines invoiced for more than the PO asked."),
            Kpi(label="Fulfilment rate", value=(fulfil if fulfil is not None else "—"),
                format="percent",
                help="Σ shipped ÷ Σ requested across matched priced lines "
                     "(>100% ⇒ net over-delivered). “—” when no matched lines."),
            Kpi(label="Orders", value=n_orders, format="int",
                help="Distinct invoices in scope."),
            Kpi(label="Avg order value", value=aov, format="currency",
                help="Product revenue ÷ invoices carrying a product line."),
        ],
        charts=[
            Chart(id="rev_month", title="Product revenue by month", kind="line",
                  x=rev_m, series=[ChartSeries(name="Revenue", data=rev_v)], y_format="currency",
                  breakdowns=[
                      _bd.by_month(c_prod, rev_m, group="product_name", value="line_total",
                                   label="Top products"),
                      _bd.by_month(c_prod, rev_m, group="container_size", value="line_total",
                                   label="By size"),
                  ]),
            Chart(id="orders_month", title="Orders by month", kind="bar",
                  x=ord_m, series=[ChartSeries(name="Orders", data=ord_v)], y_format="int",
                  breakdowns=[
                      _bd.by_month(c_prod, ord_m, group="product_name", value="invoice_id",
                                   agg="nunique", label="Products ordered", fmt="int"),
                  ]),
            Chart(id="rev_by_product", title=f"Revenue by product (top {_TOP_N})", kind="hbar",
                  x=list(by_product.index),
                  series=[ChartSeries(name="Revenue", data=[finite(v) for v in by_product.values])],
                  y_format="currency",
                  breakdowns=[
                      _bd.by_category(c_prod, list(by_product.index), key="product_name",
                                      group="container_size", value="line_total", label="By size"),
                  ]),
            Chart(id="qty_by_size", title="Quantity by container size", kind="bar",
                  x=list(by_size.index),
                  series=[ChartSeries(name="Units", data=[finite(v) for v in by_size.values])],
                  y_format="int",
                  breakdowns=[
                      _bd.by_category(c_prod, list(by_size.index), key="container_size",
                                      group="product_name", value="quantity", label="Top products",
                                      fmt="int"),
                  ]),
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
