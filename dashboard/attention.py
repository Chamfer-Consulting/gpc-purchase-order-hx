"""
Pure functions that rank "needs attention" items across the dashboard's data — no
Streamlit calls, so this is easy to reason about/test independently of the UI. See
/Users/jcaternolo/.claude/plans/golden-soaring-robin.md.

Built standalone in Phase 1; Phase 3 wires collect_attention_items() into the Home
page's digest (dashboard/views/home.py) and reuses the same severity/magnitude
conventions for the Data Quality page's category ordering
(dashboard/views/fulfillment_dataquality.py), so the surfaces never drift apart.
"""

from dataclasses import dataclass

import qbo_matcher

_SEVERITY_RANK = {"critical": 0, "serious": 1, "warning": 2, "info": 3}


@dataclass
class AttentionItem:
    severity: str      # "critical" | "serious" | "warning" | "info"
    category: str      # short machine key, e.g. "math_check", "price_anomaly"
    title: str          # human-readable one-liner shown on Home
    magnitude: float    # sort key within/across categories ($ impact, count, or days)
    page: str            # target st.Page url_path for the "review" deep link
    count: int = 1


def _math_check_items(ctx) -> list[AttentionItem]:
    failed = ctx.f_po[ctx.f_po["math_check_failed"]]
    if failed.empty:
        return []
    return [AttentionItem(
        severity="critical", category="math_check",
        title=f"{len(failed)} order(s) failed the math check",
        magnitude=len(failed), page="data_quality", count=len(failed),
    )]


def _extraction_error_items(ctx) -> list[AttentionItem]:
    errored = ctx.po_df[ctx.po_df["error"].notna()]
    if errored.empty:
        return []
    return [AttentionItem(
        severity="critical", category="extraction_error",
        title=f"{len(errored)} PDF(s) failed extraction",
        magnitude=len(errored), page="data_quality", count=len(errored),
    )]


def _price_anomaly_items(ctx) -> list[AttentionItem]:
    """Ranked by the flagged line's own dollar size (line_total) as a proxy for
    impact. Phase 3, when this is actually wired into the Home/Data Quality pages,
    should join reference_prices to compute the precise
    (unit_price - reference_price) * quantity deviation instead — that requires a
    reference-prices lookup this module doesn't have in Phase 1."""
    flagged = ctx.all_items[
        ctx.all_items["po_id"].isin(ctx.f_po["id"]) & ctx.all_items["price_anomaly"].notna()
        & (~ctx.all_items["product_name"].isin(ctx.hidden_products))
    ]
    if flagged.empty:
        return []
    total_impact = flagged["line_total"].abs().sum()
    return [AttentionItem(
        severity="serious", category="price_anomaly",
        title=f"{len(flagged)} line item(s) priced outside their reference range",
        magnitude=float(total_impact), page="data_quality", count=len(flagged),
    )]


def _requested_vs_delivered_items(matched_line_items_df, po_ids, threshold: float = 50.0) -> list[AttentionItem]:
    """matched_line_items_df: the DataFrame returned by data.load_matched_line_items()
    (one row per confirmed po<->invoice<->product<->size). threshold: minimum absolute
    $ variance for a row to count as worth surfacing."""
    if matched_line_items_df is None or matched_line_items_df.empty:
        return []
    detail = matched_line_items_df[matched_line_items_df["po_id"].isin(po_ids)].copy()
    if detail.empty:
        return []
    detail["variance"] = detail["delivered_amount"] - detail["requested_amount"]
    large = detail[detail["variance"].abs() >= threshold]
    if large.empty:
        return []
    total_variance = large["variance"].abs().sum()
    return [AttentionItem(
        severity="serious", category="fulfillment_variance",
        title=f"{len(large)} requested-vs-delivered line(s) off by ${threshold:,.0f}+",
        magnitude=float(total_variance), page="requested_vs_delivered", count=len(large),
    )]


def _needs_review_items(needs_review_rows: list[dict]) -> list[AttentionItem]:
    """needs_review_rows: qbo_matcher.get_needs_review(conn)'s return value. Uses the
    same confidence_label()/is_quick_confirm() split as the Match & Review page's
    quick-confirm/needs-judgment split, so the two surfaces never disagree on what
    counts as "quick"."""
    if not needs_review_rows:
        return []
    confidences = [qbo_matcher.confidence_label(r.get("match_method"), r.get("match_score")) for r in needs_review_rows]
    quick = [r for r, c in zip(needs_review_rows, confidences) if qbo_matcher.is_quick_confirm(c)]
    judgment = [r for r, c in zip(needs_review_rows, confidences) if not qbo_matcher.is_quick_confirm(c)]
    items = []
    if quick:
        items.append(AttentionItem(
            severity="warning", category="quick_confirm",
            title=f"{len(quick)} high-confidence match(es) just need confirming",
            magnitude=len(quick), page="match_review", count=len(quick),
        ))
    if judgment:
        items.append(AttentionItem(
            severity="info", category="needs_judgment",
            title=f"{len(judgment)} match candidate(s) need manual judgment",
            magnitude=len(judgment), page="match_review", count=len(judgment),
        ))
    return items


def _stale_unmatched_items(unlinked_pos: list[dict], stale_days: int = 30) -> list[AttentionItem]:
    """unlinked_pos: qbo_matcher.get_unlinked_pos(conn)'s return value — each row is
    expected to carry a 'po_date' or 'sent_date' the caller can use to compute age;
    left as a simple count here since age isn't available on every row shape."""
    if not unlinked_pos:
        return []
    return [AttentionItem(
        severity="warning", category="stale_unmatched",
        title=f"{len(unlinked_pos)} PO(s) still have no confirmed invoice match",
        magnitude=len(unlinked_pos), page="match_review", count=len(unlinked_pos),
    )]


def collect_attention_items(
    ctx,
    matched_line_items_df=None,
    needs_review_rows=None,
    unlinked_pos=None,
    max_items: int = 8,
) -> list[AttentionItem]:
    """Aggregates every category above, ranked by severity first, then magnitude
    within severity. Any optional data source that's omitted simply contributes no
    items for that category (callers not yet wiring in the matcher/DB-backed sources
    still get the pure-dataframe categories)."""
    items: list[AttentionItem] = []
    items += _math_check_items(ctx)
    items += _extraction_error_items(ctx)
    items += _price_anomaly_items(ctx)
    if matched_line_items_df is not None:
        items += _requested_vs_delivered_items(matched_line_items_df, ctx.f_po["id"].tolist())
    if needs_review_rows is not None:
        items += _needs_review_items(needs_review_rows)
    if unlinked_pos is not None:
        items += _stale_unmatched_items(unlinked_pos)

    items.sort(key=lambda it: (_SEVERITY_RANK.get(it.severity, 9), -it.magnitude))
    return items[:max_items]
