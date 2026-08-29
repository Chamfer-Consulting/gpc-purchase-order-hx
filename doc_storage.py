"""Optional Supabase Storage backend for captured PO/invoice PDFs.

When configured (SUPABASE_URL + a service-role key), po_doc_capture.store_document
uploads the bytes here and leaves po_documents.content NULL; reads fall back to a
download from here. When it's *not* configured every call is a no-op and bytes
stay inline in Postgres — so this is safe to ship before Supabase Storage is wired.

Direct REST calls (no supabase-py SDK) — matches qbo_client.py / gdrive_client.py.
"""

import requests

_URL = ""
_KEY = ""
_BUCKET = "po-documents"
_TIMEOUT = 60


def configure(url: str, service_key: str, bucket: str = "po-documents") -> None:
    global _URL, _KEY, _BUCKET
    _URL = (url or "").rstrip("/")
    _KEY = service_key or ""
    _BUCKET = bucket or "po-documents"


def is_enabled() -> bool:
    return bool(_URL and _KEY)


def bucket() -> str:
    return _BUCKET


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {_KEY}", "apikey": _KEY}
    if extra:
        h.update(extra)
    return h


def _object_url(path: str) -> str:
    return f"{_URL}/storage/v1/object/{_BUCKET}/{path.lstrip('/')}"


def upload(path: str, data: bytes, content_type: str = "application/pdf") -> None:
    resp = requests.post(
        _object_url(path),
        headers=_headers({"Content-Type": content_type, "x-upsert": "true"}),
        data=data,
        timeout=_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"Supabase Storage upload failed {resp.status_code}: {resp.text[:300]}")


def download(path: str) -> bytes:
    resp = requests.get(_object_url(path), headers=_headers(), timeout=_TIMEOUT)
    if not resp.ok:
        raise RuntimeError(f"Supabase Storage download failed {resp.status_code}: {resp.text[:300]}")
    return resp.content


def delete(path: str) -> None:
    resp = requests.delete(_object_url(path), headers=_headers(), timeout=_TIMEOUT)
    # 404 = already gone; treat as success
    if not resp.ok and resp.status_code != 404:
        raise RuntimeError(f"Supabase Storage delete failed {resp.status_code}: {resp.text[:300]}")
