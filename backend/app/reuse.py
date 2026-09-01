"""The backend reuses the repo's existing Python directly — the extraction /
matching / catalog logic at the repo root, plus the three shared data modules in
`shared/` (`data.py`, `qbo_client.py`, `qbo_matcher.py`, formerly under
`dashboard/`). Importing this module puts the repo root and `shared/` on
sys.path so `import qbo_matcher`, `import product_catalog`, `from data import ...`
resolve. These modules import cleanly without Streamlit.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO_ROOT = _REPO_ROOT  # public alias — e.g. services/extraction_retry.py shells out to a script here
_SHARED = os.path.join(_REPO_ROOT, "shared")

for p in (_SHARED, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
