"""Who am I + what can I do. The SPA reads this once to gate edit/admin controls."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, app_role, current_user

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: AuthedUser = Depends(current_user)) -> dict:
    return {"email": user.email, "role": app_role(user.email)}
