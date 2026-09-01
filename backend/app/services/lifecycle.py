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
from ..schemas import (
    BreakdownPoint,
    BreakdownRow,
    Chart,
    ChartBreakdown,
    ChartSeries,
    Kpi,
    PageResponse,
    Scope,
    Table,
    TableColumn,
)
from ._util import finite, records

_BREAKDOWN_TOP_N = 5

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
    m: pd.DataFrame   # scoped matched lines + lost_/over_ amount & qty columns (may be empty)
    requested: float  # Σ requested_amount (all rows)
    shipped: float    # Σ delivered_amount (all rows)
    lost: float       # Σ max(requested-delivered,0), $ over rows the PO priced
    over: float       # Σ max(delivered-requested,0), $ over rows the PO priced
    lost_units: float
    over_units: float
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
        return GapSummary(m, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for c in ("requested_qty", "requested_amount", "delivered_qty", "delivered_amount"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)
    m["lost_amount"] = (m["requested_amount"] - m["delivered_amount"]).clip(lower=0)
    m["lost_qty"] = (m["requested_qty"] - m["delivered_qty"]).clip(lower=0)
    m["over_amount"] = (m["delivered_amount"] - m["requested_amount"]).clip(lower=0)
    m["over_qty"] = (m["delivered_qty"] - m["requested_qty"]).clip(lower=0)
    # $ shortfall/overage only where the PO actually priced the line — a delivered
    # line with no priced PO counterpart (extraction gap, or an unrequested extra)
    # would otherwise dump its whole invoice value into "over".
    priced = m["requested_amount"] > 0
    req_qty = m["requested_qty"] > 0
    requested = finite(m["requested_amount"].sum())
    shipped = finite(m["delivered_amount"].sum())
    return GapSummary(
        m, requested, shipped,
        finite(m.loc[priced, "lost_amount"].sum()),
        finite(m.loc[priced, "over_amount"].sum()),
        finite(m.loc[req_qty, "lost_qty"].sum()),
        finite(m.loc[req_qty, "over_qty"].sum()),
        round(shipped / requested * 100, 1) if requested else 0.0,
    )


def _one_breakdown(m: pd.DataFrame, months: list[str], col: str, label: str) -> ChartBreakdown:
    """Per month, the top `col` values by (requested + shipped) $, each with its
    own requested / shipped split — for the requested-vs-shipped tooltip."""
    d = m.dropna(subset=["effective_date"]).copy()
    d["_m"] = d["effective_date"].dt.to_period("M").astype(str)
    d[col] = d[col].fillna("—").replace("", "—")
    pts: list[BreakdownPoint] = []
    for mo in months:
        sub = d[d["_m"] == mo]
        rows: list[BreakdownRow] = []
        if not sub.empty:
            g = (
                sub.groupby(col)
                .agg(requested=("requested_amount", "sum"), shipped=("delivered_amount", "sum"))
                .reset_index()
            )
            g = g.assign(_t=g["requested"].abs() + g["shipped"].abs())
            g = g[g["_t"] > 0].sort_values("_t", ascending=False).head(_BREAKDOWN_TOP_N)
            rows = [
                BreakdownRow(name=str(r[col]), requested=round(float(r["requested"]), 2),
                             shipped=round(float(r["shipped"]), 2))
                for _, r in g.iterrows()
            ]
        pts.append(BreakdownPoint(x=mo, rows=rows))
    return ChartBreakdown(by=col.replace("_name", ""), label=label, points=pts)


def month_breakdowns(m: pd.DataFrame, months: list[str]) -> list[ChartBreakdown]:
    """Top products + top customers behind each month of the requested-vs-shipped
    series. Empty list when there are no matched lines."""
    if m is None or m.empty or not months:
        return []
    return [
        _one_breakdown(m, months, "product_name", "Top products"),
        _one_breakdown(m, months, "customer_name", "Top customers"),
    ]


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
    requested, shipped, lost, over, lost_units, fulfil = (
        gs.requested, gs.shipped, gs.lost, gs.over, gs.lost_units, gs.fulfil
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
              ], y_format="currency",
              breakdowns=month_breakdowns(m, months) if not m.empty else None),
        Chart(id="lost_by_month", title="Under-shipped by month (requested − shipped)", kind="bar", x=months,
              series=[ChartSeries(name="Under-shipped", data=_series(months, m, "lost_amount") if not m.empty else [])],
              y_format="currency"),
    ]
    tables = {}

    if not m.empty:
        cust = (
            m.groupby("customer_name")
            .agg(requested=("requested_amount", "sum"), shipped=("delivered_amount", "sum"),
                 lost=("lost_amount", "sum"), over=("over_amount", "sum"))
            .reset_index()
        )
        cust["fulfil_pct"] = (cust["shipped"] / cust["requested"].where(cust["requested"] > 0) * 100).round(1)
        cust = cust.sort_values("lost", ascending=False)
        charts.append(Chart(
            id="lost_by_customer", title=f"Under-shipped by customer (top {_TOP_N})", kind="hbar",
            x=list(cust.head(_TOP_N)["customer_name"]),
            series=[ChartSeries(name="Under-shipped", data=[finite(v) for v in cust.head(_TOP_N)["lost"]])],
            y_format="currency"))
        tables["by_customer"] = Table(
            title=f"By customer ({cust.shape[0]})",
            columns=[
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="requested", label="Requested", kind="currency"),
                TableColumn(key="shipped", label="Shipped", kind="currency"),
                TableColumn(key="lost", label="Under-shipped $", kind="currency"),
                TableColumn(key="over", label="Over-shipped $", kind="currency"),
                TableColumn(key="fulfil_pct", label="Fulfilment %", kind="percent"),
            ],
            rows=records(cust.head(_ROW_CAP)[
                ["customer_name", "requested", "shipped", "lost", "over", "fulfil_pct"]
            ]),
            export_name="lifecycle_by_customer",
        )

        prod = (
            m.groupby(["product_name", "container_size"])
            .agg(requested_units=("requested_qty", "sum"), delivered_units=("delivered_qty", "sum"),
                 short_units=("lost_qty", "sum"), over_units=("over_qty", "sum"),
                 short_amount=("lost_amount", "sum"))
            .reset_index()
        )
        prod = prod[prod["short_amount"] > 0].sort_values("short_amount", ascending=False)
        tables["by_product"] = Table(
            title=f"Under-shipped by product ({prod.shape[0]})",
            columns=[
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="container_size", label="Size"),
                TableColumn(key="requested_units", label="Requested units", kind="int"),
                TableColumn(key="delivered_units", label="Delivered units", kind="int"),
                TableColumn(key="short_units", label="Units under", kind="int"),
                TableColumn(key="over_units", label="Units over", kind="int"),
                TableColumn(key="short_amount", label="Under-shipped $", kind="currency"),
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
            Kpi(label="Under-shipped", value=round(lost, 2), format="currency",
                help="Σ (requested − shipped) on the order lines invoiced for LESS than "
                     "the PO asked — the lost sales. An over-ship on a different order "
                     "doesn't refund a shorted one, so this exceeds the net "
                     "(Requested − Shipped)."),
            Kpi(label="Over-shipped", value=round(over, 2), format="currency",
                help="Σ (shipped − requested) on lines invoiced for MORE than the PO asked. "
                     "Under-shipped − Over-shipped = Requested − Shipped."),
            Kpi(label="Fulfilment rate", value=fulfil, format="percent",
                help="Σ shipped ÷ Σ requested across matched order lines (over-ships mask "
                     "under-ships here — see Under-shipped for the per-order view)."),
            Kpi(label="Requested", value=round(requested, 2), format="currency"),
            Kpi(label="Shipped", value=round(shipped, 2), format="currency"),
        ],
        charts=charts,
        tables=tables,
        notes=[
            "Matched PO ⇄ invoice lines are aligned by product name (sizes and the two "
            "sides' spellings vary); the requested side is taken from whichever PO "
            "revision best matches each invoice. $ figures cover only lines the PO priced.",
            "“Under-shipped” counts only order lines invoiced for less than the customer's "
            "final request; an over-ship elsewhere doesn't offset it. Per row: "
            "Requested − Delivered = Under − Over.",
            *([f"Separately, ${withdrawn:,.0f} of requested value was negotiated down or "
               "withdrawn before shipping (a PO revision) — not counted as under-shipped."]
              if withdrawn else []),
        ],
    )
