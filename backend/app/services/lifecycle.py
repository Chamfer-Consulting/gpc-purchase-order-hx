"""Order Lifecycle — the app's core question: how much of what a customer asked
for on a PO actually got shipped (invoiced), and where the gap is.

Two lenses:
  * per-order waterfall — requested (first PO version) -> revised (latest version)
    -> shipped (matched invoice). requested-revised = negotiated down / withdrawn;
    revised-shipped = the fulfilment shortfall (the "lost sales").
  * line-level gap — from load_matched_line_items(): requested vs delivered per
    (order, product, size), trended by month and broken out by customer / product.
"""

from dataclasses import dataclass

import pandas as pd

import data as _dash  # shared/data.py, via app.reuse
from qbo_matcher import customers_match  # shared/, via app.reuse

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from ._util import finite, records

_TOP_N = 12
_ROW_CAP = 300


def _months(df: pd.DataFrame) -> list[str]:
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return []
    return sorted(set(d["effective_date"].dt.to_period("M").astype(str)))


def _series(index: list[str], df: pd.DataFrame, col: str) -> list[float | None]:
    d = df.dropna(subset=["effective_date"])
    if d.empty:
        return [None] * len(index)
    g = d.assign(_m=d["effective_date"].dt.to_period("M").astype(str)).groupby("_m")[col].sum()
    return [finite(g[m]) if m in g.index else None for m in index]


@dataclass
class GapSummary:
    """Line-level requested-vs-shipped rollup, scoped to a FilterParams. Shared by
    /lifecycle and the Overview KPIs / chart."""
    m: pd.DataFrame   # scoped matched lines + lost_amount / lost_qty columns (may be empty)
    requested: float
    shipped: float
    lost: float
    lost_units: float
    fulfil: float     # shipped / requested %


def matched_gap_summary(fp: FilterParams) -> GapSummary:
    m = _dash.load_matched_line_items()
    m = m.copy() if m is not None else pd.DataFrame()
    if not m.empty:
        m["effective_date"] = pd.to_datetime(m["effective_date"], errors="coerce")
        if fp.start:
            m = m[m["effective_date"] >= pd.Timestamp(fp.start)]
        if fp.end:
            m = m[m["effective_date"] < pd.Timestamp(fp.end) + pd.Timedelta(days=1)]
        if fp.customers:
            m = m[m["customer_name"].fillna("").map(
                lambda c: any(customers_match(c, s) for s in fp.customers)
            )]
    if m.empty:
        return GapSummary(m, 0.0, 0.0, 0.0, 0.0, 0.0)
    for c in ("requested_qty", "requested_amount", "delivered_qty", "delivered_amount"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)
    m["lost_amount"] = (m["requested_amount"] - m["delivered_amount"]).clip(lower=0)
    m["lost_qty"] = (m["requested_qty"] - m["delivered_qty"]).clip(lower=0)
    requested = finite(m["requested_amount"].sum())
    shipped = finite(m["delivered_amount"].sum())
    return GapSummary(
        m, requested, shipped, finite(m["lost_amount"].sum()), finite(m["lost_qty"].sum()),
        round(shipped / requested * 100, 1) if requested else 0.0,
    )


def order_lifecycle(fp: FilterParams) -> PageResponse:
    po_df, items_df, _matched_df = _dash.load_data()
    if "status" in po_df.columns:  # admin-CRUD soft delete / cancel — out of scope
        po_df = po_df[po_df["status"].fillna("active") == "active"]
    valid_po, latest_po, _all_items, _latest_items = _dash.prepare(po_df, items_df)

    scoped = latest_po
    if fp.start:
        scoped = scoped[scoped["effective_date"] >= pd.Timestamp(fp.start)]
    if fp.end:
        scoped = scoped[scoped["effective_date"] < pd.Timestamp(fp.end) + pd.Timedelta(days=1)]
    if fp.customers:
        scoped = scoped[
            scoped["customer_name"].fillna("").map(
                lambda c: any(customers_match(c, s) for s in fp.customers)
            )
        ]
    keep_keys = set(scoped["po_key"])
    if not keep_keys:
        return PageResponse(
            scope=Scope(count=0, noun="orders", start=fp.start, end=fp.end),
            notes=["No orders in this scope."],
        )

    lc = _dash.order_lifecycle(valid_po, keep_keys, _dash.load_matched_line_items())

    # ---- line-level gap (the trending / by-customer / by-product view) ----------
    gs = matched_gap_summary(fp)
    m = gs.m
    requested, shipped, lost, lost_units, fulfil = (
        gs.requested, gs.shipped, gs.lost, gs.lost_units, gs.fulfil
    )

    # per-order waterfall totals
    o_req = pd.to_numeric(lc["requested_amount"], errors="coerce")
    o_rev = pd.to_numeric(lc["revised_amount"], errors="coerce")
    o_shp = pd.to_numeric(lc["shipped_amount"], errors="coerce")
    have_ship = o_shp.notna()
    withdrawn = finite((o_req[have_ship] - o_rev[have_ship]).clip(lower=0).sum())

    months = _months(m) if not m.empty else []
    charts = [
        Chart(id="req_vs_shipped", title="Requested vs shipped by month", kind="line", x=months,
              series=[
                  ChartSeries(name="Requested", data=_series(months, m, "requested_amount") if not m.empty else []),
                  ChartSeries(name="Shipped", data=_series(months, m, "delivered_amount") if not m.empty else []),
              ], y_format="currency"),
        Chart(id="lost_by_month", title="Lost sales by month (requested − shipped)", kind="bar", x=months,
              series=[ChartSeries(name="Lost sales", data=_series(months, m, "lost_amount") if not m.empty else [])],
              y_format="currency"),
    ]
    tables = {}

    if not m.empty:
        cust = (
            m.groupby("customer_name")
            .agg(requested=("requested_amount", "sum"), shipped=("delivered_amount", "sum"),
                 lost=("lost_amount", "sum"), lost_units=("lost_qty", "sum"))
            .reset_index()
        )
        cust["fulfil_pct"] = (cust["shipped"] / cust["requested"].where(cust["requested"] > 0) * 100).round(1)
        cust = cust.sort_values("lost", ascending=False)
        charts.append(Chart(
            id="lost_by_customer", title=f"Lost sales by customer (top {_TOP_N})", kind="hbar",
            x=list(cust.head(_TOP_N)["customer_name"]),
            series=[ChartSeries(name="Lost sales", data=[finite(v) for v in cust.head(_TOP_N)["lost"]])],
            y_format="currency"))
        tables["by_customer"] = Table(
            title=f"By customer ({cust.shape[0]})",
            columns=[
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="requested", label="Requested", kind="currency"),
                TableColumn(key="shipped", label="Shipped", kind="currency"),
                TableColumn(key="lost", label="Lost sales", kind="currency"),
                TableColumn(key="fulfil_pct", label="Fulfilment %", kind="percent"),
            ],
            rows=records(cust.head(_ROW_CAP)[["customer_name", "requested", "shipped", "lost", "fulfil_pct"]]),
            export_name="lifecycle_by_customer",
        )

        prod = (
            m.groupby(["product_name", "container_size"])
            .agg(requested_units=("requested_qty", "sum"), delivered_units=("delivered_qty", "sum"),
                 lost_units=("lost_qty", "sum"), lost_amount=("lost_amount", "sum"))
            .reset_index()
        )
        prod = prod[prod["lost_amount"] > 0].sort_values("lost_amount", ascending=False)
        tables["by_product"] = Table(
            title=f"Where the gap is, by product ({prod.shape[0]})",
            columns=[
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="container_size", label="Size"),
                TableColumn(key="requested_units", label="Requested units", kind="int"),
                TableColumn(key="delivered_units", label="Delivered units", kind="int"),
                TableColumn(key="lost_units", label="Units short", kind="int"),
                TableColumn(key="lost_amount", label="Lost sales", kind="currency"),
            ],
            rows=records(prod.head(_ROW_CAP)),
            export_name="lifecycle_by_product",
        )

    # per-order table (kept) — worst fulfilment first, so the biggest gaps are on top
    disp = lc.copy()
    _order = pd.to_numeric(disp["fulfillment_pct"], errors="coerce")
    disp = disp.assign(_o=_order).sort_values("_o", ascending=True, na_position="last").drop(columns="_o")
    for c in ("requested_amount", "revised_amount", "shipped_amount", "fulfillment_pct"):
        col = pd.to_numeric(disp[c], errors="coerce").round(2)
        disp[c] = col.where(col.notna(), None)
    _ed = pd.to_datetime(disp["effective_date"], errors="coerce")
    disp["effective_date"] = _ed.dt.strftime("%Y-%m-%d").where(_ed.notna(), None)
    tables["orders"] = Table(
        title=f"Per-order — requested → revised → shipped ({len(lc)}; "
              f"{int(have_ship.sum())} matched)",
        columns=[
            TableColumn(key="po_number", label="PO"),
            TableColumn(key="customer_name", label="Customer"),
            TableColumn(key="effective_date", label="Date", kind="date"),
            TableColumn(key="requested_amount", label="Requested", kind="currency"),
            TableColumn(key="revised_amount", label="Revised", kind="currency"),
            TableColumn(key="shipped_amount", label="Shipped", kind="currency"),
            TableColumn(key="fulfillment_pct", label="Fulfilment %", kind="percent"),
        ],
        rows=records(disp[["po_id", "po_number", "customer_name", "effective_date",
                           "requested_amount", "revised_amount", "shipped_amount",
                           "fulfillment_pct"]]),
        export_name="order_lifecycle",
    )

    return PageResponse(
        scope=Scope(count=int(len(lc)), noun="orders", start=fp.start, end=fp.end,
                    note=f"{int(have_ship.sum())} of {len(lc)} orders have a confirmed invoice match"),
        kpis=[
            Kpi(label="Lost sales", value=round(lost, 2), format="currency",
                help="Σ (requested − shipped) over matched order lines, shortfalls only. "
                     "The revenue asked for but not invoiced."),
            Kpi(label="Fulfilment rate", value=fulfil, format="percent",
                help="Shipped ÷ requested across matched order lines."),
            Kpi(label="Lost units", value=round(lost_units), format="int",
                help="Σ (requested qty − delivered qty), shortfalls only."),
            Kpi(label="Requested", value=round(requested, 2), format="currency"),
            Kpi(label="Shipped", value=round(shipped, 2), format="currency"),
        ],
        charts=charts,
        tables=tables,
        notes=(
            [f"Separately, ${withdrawn:,.0f} of requested value was negotiated down or "
             "withdrawn before shipping (a PO revision) — not counted as lost sales above."]
            if withdrawn else []
        ),
    )
