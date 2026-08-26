"""
Data Quality — the fix queue (redesign spec §05, Phase E). Trimmed to the three
things a human acts on: extraction errors, math-check failures, and price
anomalies. Revision counts / $ impact / lead time moved to Order Lifecycle.
North-star = extraction success rate.
"""

import streamlit as st

from data import load_matched_line_items
from ui_kit import data_grid, kpi_strip, metric_help, page_scaffold, scope_bar, section_card, state_chip

_CATEGORIES = [
    ("extraction_errors", "Extraction errors", "critical"),
    ("math_check", "Math-check failures", "critical"),
    ("price_anomalies", "Price anomalies", "serious"),
]


def render(ctx) -> None:
    f_po, all_items, po_df = ctx.f_po, ctx.all_items, ctx.po_df

    page_scaffold(
        "Data Quality",
        "What the extraction and sync pipeline got wrong or is missing — a queue to "
        "work through. Follows the current scope, except extraction errors (errored "
        "files often have no usable date).",
    )
    scope_bar(ctx.fs, order_count=int(f_po["id"].nunique()))

    errored = po_df[po_df["error"].notna()]
    math_fail = f_po[f_po["math_check_failed"]]
    price_issues = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["price_anomaly"].notna()
        & (~all_items["product_name"].isin(ctx.hidden_products))
    ]
    if not price_issues.empty:
        price_issues = price_issues.reindex(price_issues["line_total"].abs().sort_values(ascending=False).index)

    total_rows = max(len(po_df), 1)
    success_rate = (total_rows - len(errored)) / total_rows * 100
    matched = load_matched_line_items()
    n_po = int(f_po["id"].nunique())
    coverage = matched.loc[matched["po_id"].isin(f_po["id"]), "po_id"].nunique() / n_po * 100 if n_po else 0

    kpi_strip([
        {"label": "Extraction success", "value": f"{success_rate:.1f}%"},
        {"label": "Errors", "value": f"{len(errored):,}"},
        {"label": "Math-check failures", "value": f"{len(math_fail):,}"},
        {"label": "Price anomalies", "value": f"{len(price_issues):,}", "help": metric_help("Price anomaly")},
        {"label": "Match coverage", "value": f"{coverage:.0f}%", "help": metric_help("Match coverage")},
    ], north_star=0)

    counts = {"extraction_errors": len(errored), "math_check": len(math_fail), "price_anomalies": len(price_issues)}
    options = [f"{label} ({counts[key]})" for key, label, _ in _CATEGORIES]
    picked = st.segmented_control("Queue", options, default=options[0], key="dq_category") or options[0]
    selected = _CATEGORIES[options.index(picked)][0]
    st.divider()

    if selected == "extraction_errors":
        with section_card("Extraction errors"):
            if errored.empty:
                st.caption("None — every file extracted successfully.")
            else:
                cols = [
                    "gmail_from", "gmail_subject", "gmail_first_message_at", "gmail_last_message_at",
                    "gmail_message_count", "gmail_attachment_names", "error", "source_file", "gmail_url",
                ]
                show = errored[[c for c in cols if c in errored.columns]].rename(columns={
                    "gmail_from": "From", "gmail_subject": "Subject", "gmail_first_message_at": "First msg",
                    "gmail_last_message_at": "Last msg", "gmail_message_count": "Msgs",
                    "gmail_attachment_names": "Attachments", "error": "Error", "source_file": "Source",
                    "gmail_url": "Email",
                })
                st.dataframe(
                    show, width="stretch", hide_index=True,
                    column_config={"Email": st.column_config.LinkColumn("Email", display_text="Open ↗")},
                )
                st.caption(
                    "A `gmail-thread:…` source is a whole email conversation with no PO document; "
                    "**Open ↗** goes to the thread in Gmail. A bare filename is a PDF attachment that "
                    "extracted but wasn't classified as a purchase order."
                )
                st.download_button(
                    "Export this table (CSV)", show.to_csv(index=False).encode("utf-8"),
                    file_name="extraction_errors.csv", mime="text/csv", key="dl_errors",
                )

    elif selected == "math_check":
        with section_card("Math-check failures", "Line totals or the header total don't add up as printed."):
            if math_fail.empty:
                st.caption("None — arithmetic on every order checks out.")
            else:
                data_grid(
                    math_fail, ["po_number", "source_file", "customer_name", "math_check_detail"],
                    key="dq_math", download_name="math_check_failures.csv",
                )

    else:  # price_anomalies
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
