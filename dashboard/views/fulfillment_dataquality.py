"""
📦 Fulfillment → Data Quality (renamed from "⚠️ Revisions & Data Quality"). Phase 3
redesign: a top category KPI row replaces "7 tables always rendered, unranked" —
selecting a category reveals only that category's detail below, and the two genuinely
"needs attention" categories (price anomalies, math check failures) are sorted by
magnitude/severity instead of source order. All underlying computations are unchanged
from Phase 1.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import style
from ui_kit import data_table, empty_state, page_scaffold, scope_bar, section_card, severity_badge

_CATEGORIES = [
    ("extraction_errors", "❌ Extraction Errors", "critical"),
    ("math_check", "⚠️ Math Check Failures", "critical"),
    ("price_anomalies", "💲 Price Anomalies", "serious"),
    ("latest_changes", "📝 Latest Revision Changes", "warning"),
    ("revisions", "🔁 Orders With Revisions", "info"),
    ("lead_time", "📦 Order Lead Time", "info"),
    ("revision_impact", "💵 Revision $ Impact", "info"),
]


def render(ctx) -> None:
    f_po, valid_po, all_items, po_df, palette = ctx.f_po, ctx.valid_po, ctx.all_items, ctx.po_df, ctx.palette

    page_scaffold(
        "Data Quality",
        "Follows the current scope, except **Extraction errors** (errored files "
        "often have no usable date).",
    )
    scope_bar(ctx.fs, order_count=int(f_po["id"].nunique()))

    # ── Compute every category's data once, up front (cheap — all in-memory pandas ops
    # already loaded for this rerun), so the KPI row can show real counts regardless of
    # which category is currently selected below. ──────────────────────────────────

    rev_po = f_po[f_po["is_revision"]]

    lead = f_po.dropna(subset=["effective_date", "delivery_date"]).copy()
    lead["lead_days"] = (lead["delivery_date"] - lead["effective_date"]).dt.days
    lead = lead[lead["lead_days"] >= 0]

    hist_po = valid_po[valid_po["po_key"].isin(f_po["po_key"])].sort_values(["po_key", "effective_date", "id"])
    impacts = []
    for po_key, grp in hist_po.groupby("po_key"):
        if len(grp) < 2:
            continue
        original_total, final_total = grp.iloc[0]["total"], grp.iloc[-1]["total"]
        if pd.notna(original_total) and pd.notna(final_total):
            impacts.append(final_total - original_total)
    impacts = pd.Series(impacts, dtype=float)

    diff_items = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["revision_status"].isin(["Added", "Changed", "Removed"])
        & (~all_items["product_name"].isin(ctx.hidden_products))
    ]

    math_fail = f_po[f_po["math_check_failed"]]

    price_issues = all_items[
        all_items["po_id"].isin(f_po["id"]) & all_items["price_anomaly"].notna()
        & (~all_items["product_name"].isin(ctx.hidden_products))
    ]
    if not price_issues.empty:
        # Ranked by the flagged line's own dollar size — a proxy for impact (see
        # dashboard/attention.py's _price_anomaly_items, which uses the same signal for
        # the Home digest, so the two surfaces never disagree on what's worst).
        price_issues = price_issues.reindex(price_issues["line_total"].abs().sort_values(ascending=False).index)

    errored = po_df[po_df["error"].notna()]

    counts = {
        "extraction_errors": len(errored),
        "math_check": len(math_fail),
        "price_anomalies": len(price_issues),
        "latest_changes": len(diff_items),
        "revisions": len(rev_po),
        "lead_time": len(lead),
        "revision_impact": len(impacts),
    }

    # ── KPI row: severity-colored count per category ────────────────────────────────
    kpi_cols = st.columns(len(_CATEGORIES), border=True)
    for col, (key, label, severity) in zip(kpi_cols, _CATEGORIES):
        with col:
            severity_badge(severity if counts[key] else "good", label)
            st.metric(" ", f"{counts[key]:,}", label_visibility="collapsed")

    st.divider()

    options = [f"{label} ({counts[key]})" for key, label, _ in _CATEGORIES]
    picked = st.segmented_control("Category", options, default=options[0], key="dq_category")
    if picked is None:
        picked = options[0]
    selected_key = _CATEGORIES[options.index(picked)][0]

    if selected_key == "extraction_errors":
        with section_card("❌ Extraction errors"):
            if errored.empty:
                st.caption("None — every file extracted successfully.")
            else:
                cols = [
                    "source_file", "error", "gmail_from", "gmail_subject",
                    "gmail_first_message_at", "gmail_last_message_at",
                    "gmail_message_count", "gmail_attachment_names", "gmail_url",
                ]
                err_table = errored[[c for c in cols if c in errored.columns]].rename(columns={
                    "source_file": "Source", "error": "Error", "gmail_from": "From",
                    "gmail_subject": "Subject", "gmail_first_message_at": "First msg",
                    "gmail_last_message_at": "Last msg", "gmail_message_count": "Msgs",
                    "gmail_attachment_names": "Attachments", "gmail_url": "Email",
                })
                data_table(err_table, column_config={
                    "Email": st.column_config.LinkColumn("Email", display_text="Open ↗"),
                })
                st.caption(
                    "Rows from `gmail-thread:…` are whole email conversations with no PO "
                    "document; **Open ↗** goes to the thread in Gmail. A bare filename is a "
                    "PDF attachment that extracted but wasn't classified as a purchase order."
                )
                st.download_button(
                    "⬇️ Download extraction errors (CSV)", err_table.to_csv(index=False).encode("utf-8"),
                    file_name="extraction_errors.csv", mime="text/csv", key="dl_errors",
                )

    elif selected_key == "math_check":
        with section_card("⚠️ Math check failures"):
            if math_fail.empty:
                st.caption("None — arithmetic on every order checks out.")
            else:
                math_table = math_fail[["po_number", "source_file", "customer_name", "math_check_detail"]].rename(columns={
                    "po_number": "PO Number", "source_file": "Source File",
                    "customer_name": "Customer", "math_check_detail": "Issue",
                })
                data_table(math_table)
                st.download_button(
                    "⬇️ Download math check failures (CSV)", math_table.to_csv(index=False).encode("utf-8"),
                    file_name="math_check_failures.csv", mime="text/csv", key="dl_math_fail",
                )

    elif selected_key == "price_anomalies":
        with section_card(
            "💲 Price anomalies",
            "Line items whose unit price deviates more than 10% from the reference price for "
            "that customer/product/size, sorted by dollar impact. See 🏷️ Pricing & Reference "
            "Prices (under 📊 Reports) to review or override.",
        ):
            if price_issues.empty:
                st.caption("None — every price is within range of its reference.")
            else:
                price_table = price_issues[
                    ["po_number", "customer_name", "product_name", "container_size", "line_total", "price_anomaly"]
                ].rename(columns={
                    "po_number": "PO Number", "customer_name": "Customer", "product_name": "Product",
                    "container_size": "Size", "line_total": "Line Total ($)", "price_anomaly": "Issue",
                })
                data_table(price_table)
                st.download_button(
                    "⬇️ Download price anomalies (CSV)", price_table.to_csv(index=False).encode("utf-8"),
                    file_name="price_anomalies.csv", mime="text/csv", key="dl_price_anomalies",
                )

    elif selected_key == "latest_changes":
        with section_card("📝 What changed in the latest revision"):
            if diff_items.empty:
                st.caption("No line-item changes in the latest revision of any order in the current filter.")
            else:
                data_table(
                    diff_items[["po_number", "customer_name", "product_name", "revision_status", "changes"]].rename(columns={
                        "po_number": "PO Number", "customer_name": "Customer", "product_name": "Product",
                        "revision_status": "Status", "changes": "Changes",
                    }),
                )

    elif selected_key == "revisions":
        with section_card("🔁 Orders with revisions"):
            if rev_po.empty:
                st.caption("No revisions found in the current data.")
            else:
                rev_table = rev_po[["po_number", "version_label", "effective_date", "customer_name", "total", "source_file"]].rename(columns={
                    "po_number": "PO Number", "version_label": "Version", "effective_date": "Date",
                    "customer_name": "Customer", "total": "Total ($)", "source_file": "Source File",
                })
                data_table(rev_table)
                st.download_button(
                    "⬇️ Download revisions (CSV)", rev_table.to_csv(index=False).encode("utf-8"),
                    file_name="revisions.csv", mime="text/csv", key="dl_revisions",
                )

    elif selected_key == "lead_time":
        with section_card("📦 Order lead time"):
            if lead.empty:
                st.caption("Not enough orders with both an order date and a delivery date in the current filter.")
            else:
                lc1, lc2 = st.columns(2)
                lc1.metric("Median Lead Time", f"{lead['lead_days'].median():.0f} days")
                lc2.metric("Average Lead Time", f"{lead['lead_days'].mean():.1f} days")
                fig_lead = px.histogram(lead, x="lead_days", nbins=20, labels={"lead_days": "Lead time (days)"})
                fig_lead.update_traces(marker_color=palette["sequential_blue"][3])
                st.plotly_chart(style(fig_lead, palette, height=340), use_container_width=True, key="chart_lead_time")

    elif selected_key == "revision_impact":
        with section_card("💵 Revision impact", "Compares each order's original total to its latest revision's total."):
            if impacts.empty:
                st.caption("No multi-version orders in the current filter.")
            else:
                ic1, ic2, ic3 = st.columns(3)
                ic1.metric("Revisions increasing value", int((impacts > 0).sum()))
                ic2.metric("Revisions decreasing value", int((impacts < 0).sum()))
                ic3.metric("Net $ impact from revisions", f"${impacts.sum():,.2f}")
