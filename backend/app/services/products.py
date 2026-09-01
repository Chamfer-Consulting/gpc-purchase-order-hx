"""Products & Sizes — revenue + quantity by product and by container size, and
product mix over time. Ported from dashboard/views/reports_products.py."""

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from . import breakdown as _bd
from .context import build_context
from ._util import records

_SIZE_NULL = "(no size)"
_CHART_CAP = 20   # bars drawn on the hbar charts (tables stay full)
_MIX_SERIES = 12  # coloured products on the mix chart; the rest roll into "Other"
_EMPTY_NOTE = ("No product data for this scope — widen the date range or clear a filter. "
               "Hidden products and deleted accounts follow Settings → Visibility.")


def products_and_sizes(fp: FilterParams) -> PageResponse:
    ctx = build_context(fp)
    prod = ctx.f_prod
    if prod.empty:
        return PageResponse(
            scope=Scope(count=0, noun="invoices", start=fp.start, end=fp.end),
            notes=[_EMPTY_NOTE],
        )

    prod = prod.copy()
    prod["size_label"] = prod["container_size"].fillna("").replace("", _SIZE_NULL)

    # a product whose lines net to $0 in scope ("Garnet Mustard" — one comp'd
    # clamshell) is noise on a revenue report: drop its lines entirely so every
    # figure below (KPIs, both tables, the mix chart) reconciles. Revenue is
    # unchanged (they contributed $0); note which products dropped out.
    _rev = prod.groupby("product_name")["line_total"].sum().round(2)
    zero_rev_names = list(_rev[_rev == 0].index)
    if zero_rev_names:
        prod = prod[~prod["product_name"].isin(zero_rev_names)]

    by_product = (
        prod.groupby("product_name")
        .agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    by_size_all = (
        prod.groupby("size_label")
        .agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    by_size_real = by_size_all[by_size_all["size_label"] != _SIZE_NULL]
    # table keeps the "(no size)" row so revenue reconciles, always last;
    # the chart and the Sizes count are real sizes only.
    by_size = pd.concat([by_size_real, by_size_all[by_size_all["size_label"] == _SIZE_NULL]])

    # product mix over time (stacked bar by month) — cap the coloured series at the
    # top _MIX_SERIES products by revenue, the rest bucketed as "Other", so the
    # stack and its legend stay legible (mirrors explore._pivot_chart).
    mix_x: list[str] = []
    mix_series: list[ChartSeries] = []
    d = prod.dropna(subset=["effective_date"])
    if not d.empty:
        keep = set(by_product.head(_MIX_SERIES)["product_name"])
        d = d.assign(
            month=d["effective_date"].dt.to_period("M").astype(str),
            _s=d["product_name"].where(d["product_name"].isin(keep), "Other"),
        )
        pivot = d.pivot_table(index="month", columns="_s", values="line_total", aggfunc="sum").fillna(0.0)
        pivot = pivot.sort_index()
        # order series by total revenue, "Other" last
        order = pivot.sum().sort_values(ascending=False).index.tolist()
        order = [c for c in order if c != "Other"] + (["Other"] if "Other" in order else [])
        mix_x = list(pivot.index)
        mix_series = [
            ChartSeries(name=str(col), data=[float(v) for v in pivot[col].values]) for col in order
        ]

    total_rev = float(by_product["revenue"].sum())
    total_qty = float(by_product["quantity"].sum())
    n_sizes = int(by_size_real.shape[0])

    notes: list[str] = []
    if zero_rev_names:
        names = ", ".join(zero_rev_names[:6])
        notes.append(
            f"{len(zero_rev_names)} product(s) with no revenue in this scope are not shown "
            f"({names}) — comped / description-only clamshells."
        )

    return PageResponse(
        scope=Scope(count=int(ctx.n_invoices), noun="invoices", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label="Product revenue", value=total_rev, format="currency",
                help="Sum of product line items (category='product'); shipping / services "
                     "/ samples excluded."),
            Kpi(label="Units", value=total_qty, format="int",
                help="Clamshells summed across every container size (1oz + 8oz etc.) — "
                     "not directly comparable between sizes; see the per-size table."),
            Kpi(label="Products", value=int(by_product.shape[0]), format="int",
                help="Distinct products with revenue in scope."),
            Kpi(label="Sizes", value=n_sizes, format="int",
                help="Distinct container sizes; lines with no size aren't counted."),
        ],
        charts=[
            Chart(
                id="rev_by_product",
                title="Revenue by product" + (f" (top {_CHART_CAP})" if len(by_product) > _CHART_CAP else ""),
                kind="hbar",
                x=list(by_product.head(_CHART_CAP)["product_name"]),
                series=[ChartSeries(name="Revenue",
                                    data=[float(v) for v in by_product.head(_CHART_CAP)["revenue"]])],
                y_format="currency",
                breakdowns=[
                    _bd.by_category(prod, list(by_product.head(_CHART_CAP)["product_name"]),
                                    key="product_name", group="customer_name", value="line_total",
                                    label="Top customers"),
                ],
            ),
            Chart(
                id="rev_by_size",
                title="Revenue by container size"
                + (f" (top {_CHART_CAP})" if len(by_size_real) > _CHART_CAP else ""),
                kind="hbar",
                x=list(by_size_real.head(_CHART_CAP)["size_label"]),
                series=[ChartSeries(name="Revenue",
                                    data=[float(v) for v in by_size_real.head(_CHART_CAP)["revenue"]])],
                y_format="currency",
                breakdowns=[
                    _bd.by_category(prod, list(by_size_real.head(_CHART_CAP)["size_label"]),
                                    key="size_label", group="product_name", value="line_total",
                                    label="Top products"),
                ],
            ),
            Chart(
                id="product_mix",
                title="Product mix over time",
                kind="stacked_bar",
                x=mix_x,
                series=mix_series,
                y_format="currency",
            ),
        ],
        tables={
            "by_product": Table(
                title="Revenue & quantity by product",
                columns=[
                    TableColumn(key="product_name", label="Product"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="quantity", label="Units", kind="int"),
                ],
                rows=_round(by_product),
                export_name="by_product",
            ),
            "by_size": Table(
                title="Revenue & quantity by container size"
                + (" (incl. a “(no size)” row so revenue ties to the total)"
                   if (by_size["size_label"] == _SIZE_NULL).any() else ""),
                columns=[
                    TableColumn(key="size_label", label="Size"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="quantity", label="Units", kind="int"),
                ],
                rows=_round(by_size),
                export_name="by_size",
            ),
        },
        notes=notes,
    )


def _round(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for c in ("revenue", "quantity"):
        if c in df.columns:
            df[c] = df[c].round(2)
    return records(df)
