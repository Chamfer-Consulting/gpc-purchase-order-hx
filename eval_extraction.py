#!/usr/bin/env python3
"""
Regression gate for the PO extractor.

Replays every human-reviewed target (extraction_reviews rows that carry a
content_snapshot) through the CURRENT prompt + model + few-shot block, and scores:

  - is_po accuracy : did the extractor agree with the human verdict
                     (is_po vs not_po)?
  - field accuracy : for the rows the human marked is_po WITH a corrected payload,
                     how close are customer_name and the line-item set?

Few-shot for each replay is built from the OTHER decisions (the row under test is
excluded) so a decision can't leak its own answer.

Exit 0 if scores are at least eval_baseline.json minus TOLERANCE; exit 1 on a
regression. `--update-baseline` writes the current scores as the new baseline
(run after an intentional improvement). `--json` prints the scorecard as JSON.

Env: ANTHROPIC_API_KEY, DATABASE_URL.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
import psycopg2

import extraction_reviews
from extract_pos import _extract_from_source
from run_cloud_extraction import CLOUD_EXTRACTION_MODEL

BASELINE_PATH = Path(__file__).with_name("eval_baseline.json")
TOLERANCE = 0.02  # allow scores to dip this far below baseline before failing


def _norm_name(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _names_match(a: str | None, b: str | None) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return na == nb
    return na in nb or nb in na


def _field_score(expected: dict, got: dict) -> float:
    """0..1 for one is_po row: half customer-name, half line-item count proximity."""
    parts = []
    if expected.get("customer_name"):
        parts.append(1.0 if _names_match(expected["customer_name"], got.get("customer_name")) else 0.0)
    exp_items = expected.get("line_items") or []
    got_items = got.get("line_items") or []
    if exp_items:
        denom = max(len(exp_items), len(got_items), 1)
        parts.append(1.0 - abs(len(exp_items) - len(got_items)) / denom)
    return sum(parts) / len(parts) if parts else 1.0


def _load_baseline() -> dict:
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text())
    return {}


def run(limit: int | None, verbose: bool) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    conn = psycopg2.connect(os.environ["DATABASE_URL"])

    cases = [
        d for d in extraction_reviews.all_decisions(conn)
        if d.get("content_snapshot") and d["verdict"] in ("is_po", "not_po")
    ]
    if limit:
        cases = cases[:limit]

    verdict_hits = 0
    field_scores: list[float] = []
    misses: list[str] = []

    for d in cases:
        exclude = {(d["target_kind"], d["target_key"])}
        fewshot = extraction_reviews.build_fewshot_block(conn, exclude=exclude)
        res = _extract_from_source(
            client, f"eval:{d['target_key']}", None, None,
            text=d["content_snapshot"], extraction_method="text",
            model=CLOUD_EXTRACTION_MODEL, extra_guidance=fewshot,
        ) or {}

        got_is_po = "error" not in res
        want_is_po = d["verdict"] == "is_po"
        if got_is_po == want_is_po:
            verdict_hits += 1
        else:
            misses.append(f"{d['target_key']}: wanted {'is_po' if want_is_po else 'not_po'}, got the other")

        if want_is_po and got_is_po:
            corrected = extraction_reviews._corrected_dict(d)
            if corrected:
                fs = _field_score(corrected, res)
                field_scores.append(fs)
                if verbose and fs < 0.9:
                    misses.append(f"{d['target_key']}: field score {fs:.2f}")

    conn.close()

    n = len(cases)
    scorecard = {
        "n": n,
        "is_po_accuracy": round(verdict_hits / n, 4) if n else None,
        "field_accuracy": round(sum(field_scores) / len(field_scores), 4) if field_scores else None,
        "field_n": len(field_scores),
        "misses": misses,
    }
    return scorecard


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="score only the first N cases")
    ap.add_argument("--update-baseline", action="store_true", help="write current scores as the new baseline")
    ap.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    for var in ("ANTHROPIC_API_KEY", "DATABASE_URL"):
        if not os.environ.get(var):
            print(f"❌ {var} not set", file=sys.stderr)
            sys.exit(2)

    card = run(args.limit, args.verbose)

    if args.json:
        print(json.dumps(card, indent=2))
    else:
        print(f"cases            : {card['n']}")
        print(f"is_po accuracy   : {card['is_po_accuracy']}")
        print(f"field accuracy   : {card['field_accuracy']}  (over {card['field_n']} corrected rows)")
        for m in card["misses"]:
            print(f"  miss: {m}")

    if card["n"] == 0:
        print("no reviewed cases with a content snapshot yet — nothing to gate on.")
        sys.exit(0)

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(
            {k: card[k] for k in ("n", "is_po_accuracy", "field_accuracy", "field_n")}, indent=2
        ) + "\n")
        print(f"✅ baseline updated -> {BASELINE_PATH.name}")
        sys.exit(0)

    baseline = _load_baseline()
    if not baseline:
        print("⚠️  no baseline yet — run with --update-baseline once you're happy with these scores.")
        sys.exit(0)

    regressed = []
    for key in ("is_po_accuracy", "field_accuracy"):
        cur, base = card.get(key), baseline.get(key)
        if cur is not None and base is not None and cur < base - TOLERANCE:
            regressed.append(f"{key}: {cur} < baseline {base} - {TOLERANCE}")

    if regressed:
        print("\n❌ REGRESSION vs baseline:")
        for r in regressed:
            print(f"   {r}")
        sys.exit(1)

    print("\n✅ no regression vs baseline.")


if __name__ == "__main__":
    main()
