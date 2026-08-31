"""Typed request-level problems for the edit / review / reconcile surface.

Each carries an HTTP status, a stable machine `code`, a human `message`, and an
optional `extra` dict. `main.py` registers one handler that renders them as
`{"detail": {"code", "message", **extra}}` — the frontend keys off `.code`.
"""

from __future__ import annotations


class ApiProblem(Exception):
    status: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


class NotFound(ApiProblem):
    """Entity doesn't exist. 404."""

    status = 404
    code = "not_found"


class StaleWrite(ApiProblem):
    """The client's `expected_version` no longer matches the row — someone else
    saved in between. 409; the payload carries the current version + who/when."""

    status = 409
    code = "stale_write"

    def __init__(self, current_version: int, edited_by: str | None,
                 edited_at: str | None) -> None:
        super().__init__(
            "This order was changed by someone else since you loaded it.",
            current_version=current_version,
            edited_by=edited_by,
            edited_at=edited_at,
        )


class BadTransition(ApiProblem):
    """A status change the lifecycle state machine doesn't allow. 422."""

    status = 422
    code = "bad_transition"

    def __init__(self, from_status: str, to_status: str, allowed: list[str]) -> None:
        super().__init__(
            f"Can't move a {from_status} order to {to_status}.",
            from_status=from_status,
            to_status=to_status,
            allowed=sorted(allowed),
        )


class BulkTransitionError(ApiProblem):
    """One or more ids in a bulk status change can't transition (or don't exist).
    422 — the whole batch is rejected, nothing is committed."""

    status = 422
    code = "bulk_bad_transition"

    def __init__(self, missing: list[int], invalid: list[dict]) -> None:
        parts = []
        if invalid:
            parts.append(f"{len(invalid)} can't make that transition")
        if missing:
            parts.append(f"{len(missing)} not found")
        super().__init__(
            "Bulk status change rejected — " + ", ".join(parts) + ". Nothing was changed.",
            missing=missing,
            invalid=invalid,
        )


class NotActive(ApiProblem):
    """A content edit (lines, customer, links, regroup) attempted on a
    non-active PO. 409 — restore it first."""

    status = 409
    code = "not_active"

    def __init__(self, status: str) -> None:
        super().__init__(
            f"This order is {status}. Reactivate it before editing.",
            status=status,
        )


class DuplicatePoNumber(ApiProblem):
    """Another active PO already carries this po_number. 409."""

    status = 409
    code = "duplicate_po_number"

    def __init__(self, po_number: str) -> None:
        super().__init__(
            f"Another active order already uses PO number {po_number}.",
            po_number=po_number,
        )


class Forbidden(ApiProblem):
    """The signed-in user's role can't perform this action. 403."""

    status = 403
    code = "forbidden"

    def __init__(self, need: str, have: str) -> None:
        super().__init__(
            f"This action needs the {need} role (you have {have}).",
            need=need,
            have=have,
        )
