"""During the strangler-fig migration the backend reuses the repo's existing Python
directly — the extraction/matching/catalog logic and, transitionally, the dashboard
service functions. Importing this module puts the repo root and dashboard/ on
sys.path so `import qbo_matcher`, `import product_catalog`, `from data import ...`
resolve. Delete this once every service function has moved into app/services/."""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DASHBOARD = os.path.join(_REPO_ROOT, "dashboard")

for p in (_DASHBOARD, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
