"""The shared filtered dataset for the analytics pages — built by calling
dashboard/data.py directly (it imports headless now). Revenue is always the
product-line basis: sum(qbo_invoice_items.line_total) where category='product'
(the invariant from the dashboard-redesign notes)."""

from dataclasses import dataclass

import pandas as pd

import data as _dash  # shared/data.py, via app.reuse
from qbo_matcher import customers_match  # shared/, via app.reuse

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


def ghost_invoice_ids(items: pd.DataFrame, real_hidden: set[str]) -> set:
    """Invoice ids whose every category='product' line is a hidden product — they
    had product lines, and none survive the hidden set. Such an invoice is
    dropped from the dataset entirely (a "ghost"); a mixed invoice with at least
    one visible product line is kept."""
    if not real_hidden:
        return set()
    prod_lines = items[items["category"] == "product"]
    had = set(prod_lines["invoice_id"])
    kept = set(prod_lines[~prod_lines["product_name"].isin(real_hidden)]["invoice_id"])
    return had - kept


def prepared_frames(fp: FilterParams) -> tuple[pd.DataFrame, pd.DataFrame, set[str]]:
    """Everything build_context does EXCEPT the date range: load, prepare, apply the
    customer / product / size / sample / hidden filters. A caller that needs more
    than one date window over the same base (Overview's prev-period deltas) slices
    these once instead of re-querying per window."""
    inv_df, inv_items_df = _dash.load_invoice_data()
    inv, items = _dash.prepare_invoices(inv_df, inv_items_df)
    # `real_hidden` = products a human hid in Settings; `hidden` also folds in the
    # data-quality "UNKNOWN" bucket for line-level filtering. Only `real_hidden`
    # ghosts an invoice (see below) — UNKNOWN stays line-level-only.
    real_hidden = set(_dash.load_hidden_products())
    hidden = real_hidden | {"UNKNOWN"}

    # persistent customer visibility — a hidden customer drops out of every page
    hidden_cust = set(_dash.load_hidden_customers())
    if hidden_cust:
        inv = inv[~inv["customer_name"].fillna("").isin(hidden_cust)]
        items = items[items["invoice_id"].isin(inv["id"])]

    # Ghost invoices: an invoice whose *every* product line is a hidden product
    # contributes nothing, so drop it entirely (invoice count / gross adjust too).
    # A mixed invoice — at least one still-visible product line — is kept; only
    # the hidden lines are netted out of the revenue math (below).
    if real_hidden:
        ghost_ids = ghost_invoice_ids(items, real_hidden)
        if ghost_ids:
            inv = inv[~inv["id"].isin(ghost_ids)]
            items = items[~items["invoice_id"].isin(ghost_ids)]

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

    return inv, prod, hidden


def slice_by_date(
    inv: pd.DataFrame, prod: pd.DataFrame, start: str | pd.Timestamp | None, end: str | pd.Timestamp | None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restrict already-filtered frames to [start, end] on effective_date (end
    inclusive). Either bound may be None."""
    if start is not None:
        s = pd.Timestamp(start)
        inv = inv[inv["effective_date"] >= s]
        prod = prod[prod["effective_date"] >= s]
    if end is not None:
        e = pd.Timestamp(end) + pd.Timedelta(days=1)
        inv = inv[inv["effective_date"] < e]
        prod = prod[prod["effective_date"] < e]
    return inv, prod


def build_context(fp: FilterParams) -> Context:
    inv, prod, hidden = prepared_frames(fp)
    inv, prod = slice_by_date(inv, prod, fp.start, fp.end)
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
