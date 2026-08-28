"""The shared filtered dataset for the analytics pages — built by calling
dashboard/data.py directly (it imports headless now). Revenue is always the
product-line basis: sum(qbo_invoice_items.line_total) where category='product'
(the invariant from the dashboard-redesign notes)."""

from dataclasses import dataclass

import pandas as pd

import data as _dash  # dashboard/data.py, via app.reuse
from qbo_matcher import customers_match  # dashboard/, via app.reuse

from ..deps import FilterParams


@dataclass
class Context:
    f_inv: pd.DataFrame          # filtered invoices (voided already dropped by prepare_invoices)
    f_prod: pd.DataFrame         # filtered product line items (category='product')
    hidden: set[str]
    fp: FilterParams

    @property
    def revenue(self) -> float:
        return float(self.f_prod["line_total"].sum()) if not self.f_prod.empty else 0.0

    @property
    def n_invoices(self) -> int:
        return int(self.f_inv["id"].nunique()) if not self.f_inv.empty else 0


def build_context(fp: FilterParams) -> Context:
    inv_df, inv_items_df = _dash.load_invoice_data()
    inv, items = _dash.prepare_invoices(inv_df, inv_items_df)
    hidden = set(_dash.load_hidden_products()) | {"UNKNOWN"}

    # date range on effective_date
    if fp.start:
        inv = inv[inv["effective_date"] >= pd.Timestamp(fp.start)]
        items = items[items["effective_date"] >= pd.Timestamp(fp.start)]
    if fp.end:
        end = pd.Timestamp(fp.end) + pd.Timedelta(days=1)
        inv = inv[inv["effective_date"] < end]
        items = items[items["effective_date"] < end]

    # customer filter — fuzzy (PO short names vs invoice long names)
    if fp.customers:
        def _match(name: str) -> bool:
            return any(customers_match(name, sel) for sel in fp.customers)

        inv = inv[inv["customer_name"].fillna("").map(_match)]
        items = items[items["invoice_id"].isin(inv["id"])]

    # product line items on the product-revenue basis
    prod = items[items["category"] == "product"].copy()
    if not fp.include_samples and "is_sample" in prod.columns:
        prod = prod[~prod["is_sample"].fillna(False)]
    prod = prod[~prod["product_name"].isin(hidden)]

    if fp.products:
        prod = prod[prod["product_name"].isin(fp.products)]
    if fp.sizes:
        prod = prod[prod["container_size"].isin(fp.sizes)]

    if fp.products or fp.sizes:
        inv = inv[inv["id"].isin(prod["invoice_id"])]

    return Context(f_inv=inv, f_prod=prod, hidden=hidden, fp=fp)


def monthly_revenue(prod: pd.DataFrame) -> tuple[list[str], list[float]]:
    if prod.empty:
        return [], []
    d = prod.dropna(subset=["effective_date"]).copy()
    if d.empty:
        return [], []
    d["month"] = d["effective_date"].dt.to_period("M").astype(str)
    g = d.groupby("month")["line_total"].sum().sort_index()
    return list(g.index), [float(v) for v in g.values]
