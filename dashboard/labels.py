"""
One place for how raw dataframe columns and domain terms are shown to people.

Every view used to carry its own `.rename(columns={...})` map, so "source_file"
showed up as "Source File" on one page and "Order" on another, and currency
columns were formatted inconsistently (some "$", some raw float). `ui_kit.data_grid`
now looks columns up here instead — see the redesign spec §04.

- COLUMN_LABELS : raw column name -> human label
- COLUMN_KIND   : raw column name -> "currency" | "percent" | "int" | "date" |
                  "qty" | "text"  (drives auto column_config in data_grid)
- GLOSSARY      : term -> one-line definition, surfaced as `help=` tooltips
"""

from __future__ import annotations

COLUMN_LABELS: dict[str, str] = {
    # purchase order header
    "po_number": "PO #",
    "source_file": "Order",
    "effective_date": "Order date",
    "po_date": "PO date",
    "sent_date": "Sent",
    "delivery_date": "Delivery date",
    "document_printed_at": "PO printed",
    "source_received_at": "Received",
    "customer_name": "Customer",
    "customer_id": "Customer ID",
    "subtotal": "Subtotal",
    "tax": "Tax",
    "total": "PO total",
    "notes": "Notes",
    "error": "Error",
    "is_revision": "Revised",
    "version_label": "Version",
    "revision_number": "Rev #",
    "revision_label": "Rev label",
    "math_check_failed": "Math check failed",
    "math_check_detail": "Issue",
    "edited": "Edited",
    "edited_at": "Edited at",
    # line items
    "product_name": "Product",
    "product_raw": "Product (as written)",
    "container_size": "Size",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit price",
    "additional_cost": "Add'l cost",
    "line_total": "Line total",
    "is_sample": "Sample",
    "needs_review": "Review",
    "math_mismatch": "Math check",
    "price_anomaly": "Price flag",
    "revision_status": "Change",
    "category": "Line type",
    # quickbooks invoices
    "doc_number": "Invoice #",
    "txn_date": "Invoice date",
    "ship_date": "Ship date",
    "due_date": "Due date",
    "total_amt": "Invoiced",
    "private_note": "Private note",
    "item_type": "QBO type",
    "active": "Active",
    "name": "Name",
    "list_price": "List price",
    # matched / requested-vs-shipped
    "requested_qty": "Requested qty",
    "requested_amount": "Requested $",
    "delivered_qty": "Shipped qty",
    "delivered_amount": "Shipped $",
    "revised_amount": "Revised $",
    "invoiced_amount": "Invoiced $",
    "po_math_note": "PO math note",
    "po_math_notes": "PO math note",
    "line_items_sum": "Line items Σ",
    "difference": "Difference",
    "variance": "Variance",
    "po_total": "PO total",
    "po_customer": "PO customer",
    "invoice_customer": "Invoice customer",
    "invoice_date": "Invoice date",
    "invoice_total": "Invoice total",
    "day_gap": "Day gap",
    "reason": "Flagged for",
    "fulfillment_pct": "Fulfilment %",
    "match_method": "Match method",
    "match_score": "Match score",
    "match_confidence": "Confidence",
    # aggregates the views compute
    "revenue": "Revenue",
    "orders": "Orders",
    "invoices": "Invoices",
    "quantity_total": "Qty",
    "avg_order_value": "Avg order",
    "avg_invoice_value": "Avg invoice",
    "n_lines": "# lines",
    "prev": "Previous",
    "curr": "Current",
    "delta": "Change",
    "Change": "Change",
    "period_a": "Period A",
    "period_b": "Period B",
    # reference prices
    "price": "Reference price",
    "source": "Source",
    # gmail thread metadata (added with the extraction-traceability work)
    "gmail_from": "From",
    "gmail_subject": "Subject",
    "gmail_first_message_at": "First message",
    "gmail_last_message_at": "Last message",
    "gmail_message_count": "Messages",
    "gmail_attachment_names": "Attachments",
    "gmail_url": "Email",
    "gmail_thread_id": "Thread ID",
}

COLUMN_KIND: dict[str, str] = {
    "subtotal": "currency", "tax": "currency", "total": "currency",
    "unit_price": "currency", "additional_cost": "currency", "line_total": "currency",
    "total_amt": "currency", "list_price": "currency", "price": "currency",
    "requested_amount": "currency", "delivered_amount": "currency",
    "revised_amount": "currency", "invoiced_amount": "currency", "variance": "currency",
    "line_items_sum": "currency", "difference": "currency",
    "invoice_total": "currency", "day_gap": "int",
    "revenue": "currency", "avg_order_value": "currency", "avg_invoice_value": "currency",
    "prev": "currency", "curr": "currency", "delta": "currency",
    "period_a": "currency", "period_b": "currency",
    "po_total": "currency",
    "fulfillment_pct": "percent", "match_score": "percent",
    "quantity": "qty", "requested_qty": "qty", "delivered_qty": "qty",
    "quantity_total": "qty",
    "orders": "int", "invoices": "int", "n_lines": "int", "gmail_message_count": "int",
    "revision_number": "int",
    # Explore's computed pivot columns (named by the measure's display label)
    "Revenue ($)": "currency", "Quantity": "qty", "Orders": "int", "Period": "date",
    "effective_date": "date", "po_date": "date", "sent_date": "date",
    "delivery_date": "date", "txn_date": "date", "ship_date": "date", "due_date": "date",
    "document_printed_at": "date", "source_received_at": "date", "edited_at": "date",
    "gmail_first_message_at": "date", "gmail_last_message_at": "date",
}

# Invoice-line categories from classify_qbo_item, grouped for the filter bar's
# "line type" control. "product" is real sales; everything else is booked apart.
LINE_TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "Sales": ("product",),
    "Donations": ("donation",),
    "Shipping": ("delivery",),
    "Samples": ("sample",),
    "Other": ("service", "other"),
}

GLOSSARY: dict[str, str] = {
    "Revenue": "Sum of QuickBooks invoice lines categorised as product sales. "
               "Excludes donations, delivery/shipping charges, and samples.",
    "Gross invoiced": "Every QuickBooks invoice line, all categories. A reconciliation "
                      "total only — not the same as revenue.",
    "Donations": "Invoice lines categorised as donation, summed from the raw invoice "
                 "data. Almost always booked on their own $0 invoices (a product line "
                 "plus an offsetting negative donation line), so they sit outside gross "
                 "invoiced and carry no shipping charge.",
    "Shipping": "Invoice lines categorised as delivery. Shown on its own, and "
                "attributed to the linked PO where one exists.",
    "Requested": "The line items and amounts on the first version of a purchase order.",
    "Revised": "The line items and amounts on the latest version of that same PO, "
               "after any customer changes.",
    "Shipped value": "Value of matched invoice line items for orders with a confirmed "
                     "PO-to-invoice link. A subset of revenue.",
    "Fulfilment %": "Shipped $ divided by requested $ for the same order. 100% means "
                    "everything requested was delivered.",
    "North-star": "The single metric a page exists to move. Shown first, larger, with "
                  "an accent underline.",
    "Compare to": "The baseline every delta on the page is measured against — the "
                  "previous period of equal length, or the same dates a year earlier.",
    "Order": "One purchase order. Shown by its PO number, or by the email subject and "
             "sender when the order was placed conversationally with no PO document.",
    "Match coverage": "Share of orders that have a confirmed link to a QuickBooks invoice.",
    "Price anomaly": "A line whose unit price is more than 10% off the reference price "
                     "for that customer, product, and size.",
    "Lead time": "Days between the order date and the delivery date.",
}


def label(col: str) -> str:
    """Human label for a raw column name; falls back to a title-cased version."""
    if col in COLUMN_LABELS:
        return COLUMN_LABELS[col]
    return col.replace("_", " ").strip().capitalize()


def relabel(df, only: list[str] | None = None):
    """Return a copy of df with columns renamed via COLUMN_LABELS. If `only` is
    given, non-listed columns are dropped (in the given order) first."""
    if only is not None:
        df = df[[c for c in only if c in df.columns]]
    return df.rename(columns={c: label(c) for c in df.columns})


def help_for(term: str) -> str | None:
    """Glossary tooltip text for a term/label, or None."""
    return GLOSSARY.get(term)
