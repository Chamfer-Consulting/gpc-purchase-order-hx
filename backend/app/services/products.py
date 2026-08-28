"""Products & Sizes — revenue + quantity by product and by container size, and
product mix over time. Ported from dashboard/views/reports_products.py."""

import pandas as pd

from ..deps import FilterParams
from ..schemas import Chart, ChartSeries, Kpi, PageResponse, Scope, Table, TableColumn
from .context import build_context

_SIZE_NULL = "(no size)"


def products_and_sizes(fp: FilterParams) -> PageResponse:
    ctx = build_context(fp)
    prod = ctx.f_prod
    if prod.empty:
        return PageResponse(scope=Scope(count=0, noun="POs", start=fp.start, end=fp.end))

    prod = prod.copy()
    prod["size_label"] = prod["container_size"].fillna("").replace("", _SIZE_NULL)

    by_product = (
        prod.groupby("product_name")
        .agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    by_size = (
        prod.groupby("size_label")
        .agg(revenue=("line_total", "sum"), quantity=("quantity", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )

    # product mix over time (stacked bar by month)
    mix_x: list[str] = []
    mix_series: list[ChartSeries] = []
    d = prod.dropna(subset=["effective_date"])
    if not d.empty:
        d = d.assign(month=d["effective_date"].dt.to_period("M").astype(str))
        pivot = d.pivot_table(index="month", columns="product_name", values="line_total", aggfunc="sum").fillna(0.0)
        pivot = pivot.sort_index()
        mix_x = list(pivot.index)
        mix_series = [
            ChartSeries(name=str(col), data=[float(v) for v in pivot[col].values]) for col in pivot.columns
        ]

    total_rev = float(by_product["revenue"].sum())
    total_qty = float(by_product["quantity"].sum())

    return PageResponse(
        scope=Scope(count=int(ctx.n_invoices), noun="invoices", start=fp.start, end=fp.end),
        kpis=[
            Kpi(label="Product revenue", value=total_rev, format="currency"),
            Kpi(label="Units", value=total_qty, format="int"),
            Kpi(label="Products", value=int(by_product.shape[0]), format="int"),
            Kpi(label="Sizes", value=int(by_size.shape[0]), format="int"),
        ],
        charts=[
            Chart(
                id="rev_by_product",
                title="Revenue by product",
                kind="hbar",
                x=list(by_product["product_name"]),
                series=[ChartSeries(name="Revenue", data=[float(v) for v in by_product["revenue"]])],
                y_format="currency",
            ),
            Chart(
                id="rev_by_size",
                title="Revenue by container size",
                kind="hbar",
                x=list(by_size["size_label"]),
                series=[ChartSeries(name="Revenue", data=[float(v) for v in by_size["revenue"]])],
                y_format="currency",
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
                title="Revenue & quantity by container size",
                columns=[
                    TableColumn(key="size_label", label="Size"),
                    TableColumn(key="revenue", label="Revenue", kind="currency"),
                    TableColumn(key="quantity", label="Units", kind="int"),
                ],
                rows=_round(by_size),
                export_name="by_size",
            ),
        },
    )


def _round(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for c in ("revenue", "quantity"):
        if c in df.columns:
            df[c] = df[c].round(2)
    return df.to_dict("records")
