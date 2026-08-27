"""
Data Quality — the fix queue (redesign spec §05, Phase E). The things a human acts
on: extraction failures, math-check failures, price anomalies, and (reference only)
historical invoice/line-item discrepancies. North-star = extraction success rate,
counting only genuine failures — a Gmail thread correctly classified "not a
purchase order" is the pipeline working, not a failure.
"""

import streamlit as st

from data import load_invoice_reconciliation, load_matched_line_items
from ui_kit import data_grid, kpi_strip, metric_help, page_scaffold, scope_bar, section_card

_NOT_PO = "not a purchase order"

# (key, label, severity) — label is stable (no counts), so a changing count can't
# invalidate the segmented-control's persisted selection.
_CATEGORIES = [
    ("extraction_errors", "Extraction failures", "critical"),
    ("math_check", "Math-check failures", "critical"),
    ("price_anomalies", "Price anomalies", "serious"),
    ("invoice_recon", "Invoice ≠ line items", "warning"),
]


def render(ctx) -> None:
    f_po, all_items, po_df = ctx.f_po, ctx.all_items, ctx.po_df

    page_scaffold(
        "Data Quality",
        "What the extraction and sync pipeline got wrong or is missing — a queue to "
        "work through. Follows the current scope, except extraction failures (errored "
        "sources often have no usable date).",
    )
    scope_bar(ctx.fs, order_count=int(f_po["id"].nunique()), count_noun="POs")

    # A row with error = "not a purchase order" is the extractor reviewing a Gmail
    # thread and correctly deciding it is not an order — informational, not a failure.
    errored = po_df[po_df["error"].notna()]
    not_po = errored[errored["error"] == _NOT_PO]
    real_errors = errored[errored["error"] != _NOT_PO]

    # Math-check: the PO header flag (purchase_orders.math_check_failed) is not
    # populated in Postgres, so read the line-level flag that is — line_items.math_mismatch
    # — and union any header-flagged POs that aren't already covered.
    math_lines = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["math_mismatch"].notna()
        & (~all_items["product_name"].isin(ctx.hidden_products))
        & (~all_items["is_removed"].fillna(False))
    ]
    math_headers = f_po[f_po["math_check_failed"] & (~f_po["id"].isin(math_lines["po_id"]))]
    math_count = len(math_lines) + len(math_headers)

    price_issues = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["price_anomaly"].notna()
        & (~all_items["product_name"].isin(ctx.hidden_products))
        & (~all_items["is_removed"].fillna(False))
    ]
    if not price_issues.empty:
        price_issues = price_issues.reindex(price_issues["line_total"].abs().sort_values(ascending=False).index)

    # QBO invoices whose header total doesn't match their line items — scoped to the
    # current date range / customers (extraction failures above deliberately aren't).
    recon = load_invoice_reconciliation()
    if ctx.start_ts is not None and ctx.end_ts is not None:
        recon = recon[(recon["txn_date"] >= ctx.start_ts) & (recon["txn_date"] <= ctx.end_ts)]
    if ctx.selected_customers:
        recon = recon[recon["customer_name"].isin(ctx.selected_customers)]

    total_rows = max(len(po_df), 1)
    success_rate = (total_rows - len(real_errors)) / total_rows * 100
    matched = load_matched_line_items()
    n_po = int(f_po["id"].nunique())
    matched_po = matched.loc[matched["po_id"].isin(f_po["id"]), "po_id"].nunique()
    coverage = matched_po / n_po * 100 if n_po else 0

    kpi_strip([
        {"label": "Extraction success", "value": f"{success_rate:.1f}%", "delta_help": "all time"},
        {"label": "Extraction failures", "value": f"{len(real_errors):,}",
         "delta_help": f"+{len(not_po)} classified 'not a PO'" if len(not_po) else "all time"},
        {"label": "Math-check failures", "value": f"{math_count:,}"},
        {"label": "Price anomalies", "value": f"{len(price_issues):,}", "help": metric_help("Price anomaly")},
        {"label": "Invoice ≠ lines", "value": f"{len(recon):,}"},
        {"label": "Match coverage", "value": f"{coverage:.0f}%", "help": metric_help("Match coverage")},
    ], north_star=0)

    if n_po and matched_po < n_po:
        target = ctx.pages.get("match_review")
        st.caption(f"{n_po - matched_po} PO(s) in scope have no confirmed invoice match.")
        if target is not None:
            st.page_link(target, label="Resolve on Match & Reconcile →")

    counts = {
        "extraction_errors": len(real_errors), "math_check": math_count,
        "price_anomalies": len(price_issues), "invoice_recon": len(recon),
    }
    labels = {key: label for key, label, _ in _CATEGORIES}
    keys = [key for key, _, _ in _CATEGORIES]
    selected = st.segmented_control(
        "Queue", keys, default=keys[0], key="dq_category", selection_mode="single",
        format_func=lambda k: f"{labels[k]} ({counts[k]})",
    ) or keys[0]
    st.divider()

    if selected == "extraction_errors":
        with section_card("Extraction failures", "Sources that errored or timed out during extraction."):
            if real_errors.empty:
                st.caption("None — every source that should have extracted did.")
            else:
                cols = [
                    "gmail_from", "gmail_subject", "gmail_first_message_at", "gmail_last_message_at",
                    "gmail_message_count", "gmail_attachment_names", "error", "source_file", "gmail_url",
                ]
                show = real_errors[[c for c in cols if c in real_errors.columns]].rename(columns={
                    "gmail_from": "From", "gmail_subject": "Subject", "gmail_first_message_at": "First msg",
                    "gmail_last_message_at": "Last msg", "gmail_message_count": "Msgs",
                    "gmail_attachment_names": "Attachments", "error": "Error", "source_file": "Source",
                    "gmail_url": "Email",
                })
                st.dataframe(
                    show, width="stretch", hide_index=True,
                    column_config={"Email": st.column_config.LinkColumn("Email", display_text="Open ↗")},
                )
                st.download_button(
                    "Export this table (CSV)", show.to_csv(index=False).encode("utf-8"),
                    file_name="extraction_failures.csv", mime="text/csv", key="dl_errors",
                )
        if not not_po.empty:
            with st.expander(f"{len(not_po)} source(s) reviewed and classified 'not a purchase order' (not failures)"):
                npcols = ["gmail_from", "gmail_subject", "gmail_last_message_at", "source_file", "gmail_url"]
                npshow = not_po[[c for c in npcols if c in not_po.columns]].rename(columns={
                    "gmail_from": "From", "gmail_subject": "Subject", "gmail_last_message_at": "Last msg",
                    "source_file": "Source", "gmail_url": "Email",
                })
                st.dataframe(
                    npshow, width="stretch", hide_index=True,
                    column_config={"Email": st.column_config.LinkColumn("Email", display_text="Open ↗")},
                )

    elif selected == "math_check":
        with section_card("Math-check failures", "Line totals or the header total don't add up as printed."):
            if math_count == 0:
                st.caption("None — arithmetic on every order in scope checks out.")
            else:
                if not math_lines.empty:
                    data_grid(
                        math_lines,
                        ["po_number", "customer_name", "product_name", "container_size",
                         "quantity", "unit_price", "line_total", "math_mismatch"],
                        key="dq_math_lines", download_name="math_check_line_failures.csv",
                    )
                if not math_headers.empty:
                    st.caption("Header totals that don't reconcile:")
                    data_grid(
                        math_headers, ["po_number", "source_file", "customer_name", "math_check_detail"],
                        key="dq_math_hdr", download_name="math_check_header_failures.csv",
                    )

    elif selected == "price_anomalies":
        with section_card(
            "Price anomalies",
            "Unit price more than 10% off the reference price for that customer / product / size, "
            "biggest dollar lines first. Set references in Settings → Reference prices.",
        ):
            if price_issues.empty:
                st.caption("None — every price is within range of its reference.")
            else:
                data_grid(
                    price_issues,
                    ["po_number", "customer_name", "product_name", "container_size", "line_total", "price_anomaly"],
                    key="dq_price", download_name="price_anomalies.csv",
                )

    else:  # invoice_recon
        with section_card(
            "Invoice total ≠ sum of line items",
            "QuickBooks invoices whose header total doesn't match their line items (or that "
            "carry a total but no line items) — a QBO-side quirk that stops line-item revenue "
            "views (Products, Explore) reconciling to gross invoiced. Reference only.",
        ):
            if recon.empty:
                st.caption("None in this scope. (All known entries are pre-2024 records, mostly for "
                           "since-deleted customers — widen the date range to see them.)")
            else:
                st.caption(
                    "These are historical: nearly all are pre-2024 and for customers since deleted "
                    "in QuickBooks. Nothing to fix here — kept for reconciliation."
                )
                data_grid(
                    recon,
                    ["doc_number", "customer_name", "txn_date", "total_amt", "line_items_sum",
                     "n_lines", "difference"],
                    key="dq_recon", download_name="invoice_reconciliation.csv",
                )
