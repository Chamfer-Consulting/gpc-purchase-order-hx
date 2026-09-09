"""customer_alias — canonical company-name resolution. Pure, no DB."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401 — repo root on sys.path

import customer_alias  # noqa: E402
from qbo_matcher import customers_match_aliased  # noqa: E402

# "Sean McLaughlin" is a buyer at Anthony Marano Company; "David Jedlecki" a buyer
# at Midwest Foods. canonical_name is always the company.
AMAP = {
    "Anthony Marano Company": "Anthony Marano Company",
    "Anthony Marano Co. (Sean McLaughlin)": "Anthony Marano Company",
    "Sean McLaughlin / Anthony Marano Co.": "Anthony Marano Company",
    "David Jedlecki": "Midwest Foods",
    "Midwest Foods": "Midwest Foods",
    "Bill & Chris": "Skoufis Food Service",
}


def test_canonical_exact_and_ci_and_miss():
    assert customer_alias.canonical("David Jedlecki", AMAP) == "Midwest Foods"
    # whitespace / case insensitive
    assert customer_alias.canonical("  david   JEDLECKI ", AMAP) == "Midwest Foods"
    # unknown -> trimmed input, unchanged (still shown, just not folded)
    assert customer_alias.canonical("Brand New Customer", AMAP) == "Brand New Customer"
    assert customer_alias.canonical(None, AMAP) is None
    assert customer_alias.canonical("   ", AMAP) is None


def test_ci_index_reused_in_a_loop():
    idx = customer_alias._ci_index(AMAP)
    names = ["david jedlecki", "SEAN MCLAUGHLIN / ANTHONY MARANO CO.", "nobody"]
    out = [customer_alias.canonical(n, AMAP, idx) for n in names]
    assert out == ["Midwest Foods", "Anthony Marano Company", "nobody"]


def test_customers_match_aliased_folds_buyer_to_company():
    resolve = lambda n: customer_alias.canonical(n, AMAP)  # noqa: E731
    # buyer name vs company — raw customers_match would say False (no substring)
    assert not customers_match_aliased("David Jedlecki", "Midwest Foods")
    assert customers_match_aliased("David Jedlecki", "Midwest Foods", resolve)
    assert customers_match_aliased("Bill & Chris", "Skoufis Food Service", resolve)


def test_customers_match_aliased_never_removes_a_substring_match():
    resolve = lambda n: customer_alias.canonical(n, {})  # empty map  # noqa: E731
    assert customers_match_aliased("Get Fresh", "Get Fresh Produce, Inc.", resolve)
    # two blanks / unrelated names still don't match
    assert not customers_match_aliased(None, None, resolve)
    assert not customers_match_aliased("Acme", "Zenith", resolve)
