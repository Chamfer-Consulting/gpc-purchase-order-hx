"""Order Lifecycle — requested vs. revised vs. shipped per PO, and the fulfilment
rate over the matched subset. Ported from dashboard/views/order_lifecycle.py,
built on dashboard/data.py's prepare / order_lifecycle / load_matched_line_items."""

import pandas as pd

import data as _dash  # dashboard/data.py, via app.reuse
from qbo_matcher import customers_match  # dashboard/, via app.reuse

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from ._util import records


def order_lifecycle(fp: FilterParams) -> PageResponse:
    po_df, items_df, _matched_df = _dash.load_data()
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
        return PageResponse(scope=Scope(count=0, noun="orders", start=fp.start, end=fp.end))

    matched = _dash.load_matched_line_items()
    lc = _dash.order_lifecycle(valid_po, keep_keys, matched)

    req = pd.to_numeric(lc["requested_amount"], errors="coerce")
    rev = pd.to_numeric(lc["revised_amount"], errors="coerce")
    shp = pd.to_numeric(lc["shipped_amount"], errors="coerce")
    have_ship = shp.notna()

    total_rev = float(rev.sum(skipna=True))
    total_shp = float(shp.sum(skipna=True))
    fulfil_rate = round(
        (shp[have_ship].sum() / rev[have_ship].sum() * 100) if rev[have_ship].sum() else 0.0, 1
    )
    shortfall = float((rev[have_ship] - shp[have_ship]).clip(lower=0).sum())

    # shipped by month
    d = lc.dropna(subset=["effective_date"]).copy()
    months: list[str] = []
    shipped_series: list[float] = []
    if not d.empty:
        d["month"] = pd.to_datetime(d["effective_date"]).dt.to_period("M").astype(str)
        g = d.groupby("month")["shipped_amount"].sum().sort_index()
        months = list(g.index)
        shipped_series = [float(v) for v in g.values]

    disp = lc.copy()
    for c in ("requested_amount", "revised_amount", "shipped_amount", "fulfillment_pct"):
        col = pd.to_numeric(disp[c], errors="coerce").round(2)
        disp[c] = col.where(col.notna(), None)  # NaN -> None (invalid in JSON otherwise)
    _ed = pd.to_datetime(disp["effective_date"], errors="coerce")
    disp["effective_date"] = _ed.dt.strftime("%Y-%m-%d").where(_ed.notna(), None)

    return PageResponse(
        scope=Scope(count=int(len(lc)), noun="orders", start=fp.start, end=fp.end,
                    note=f"{int(have_ship.sum())} of {len(lc)} have a confirmed invoice match"),
        kpis=[
            Kpi(label="Revised order value", value=round(total_rev, 2), format="currency"),
            Kpi(label="Shipped value", value=round(total_shp, 2), format="currency"),
            Kpi(label="Fulfilment rate", value=fulfil_rate, format="percent",
                help="shipped ÷ revised over orders with a confirmed match"),
            Kpi(label="Shortfall", value=round(shortfall, 2), format="currency"),
        ],
        charts=[
            Chart(id="shipped_by_month", title="Shipped value by month", kind="bar", x=months,
                  series=[ChartSeries(name="Shipped", data=shipped_series)], y_format="currency"),
        ],
        tables={
            "orders": Table(
                title="Per-order lifecycle",
                columns=[
                    TableColumn(key="po_number", label="PO"),
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="effective_date", label="Date", kind="date"),
                    TableColumn(key="requested_amount", label="Requested", kind="currency"),
                    TableColumn(key="revised_amount", label="Revised", kind="currency"),
                    TableColumn(key="shipped_amount", label="Shipped", kind="currency"),
                    TableColumn(key="fulfillment_pct", label="Fulfilment %", kind="percent"),
                ],
                rows=records(disp[
                    ["po_id", "po_number", "customer_name", "effective_date",
                     "requested_amount", "revised_amount", "shipped_amount", "fulfillment_pct"]
                ]),
                export_name="order_lifecycle",
            )
        },
    )
