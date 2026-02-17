"""
Auth API: endpoint to verify the current user (useful for testing and frontend).
"""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import User, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(current_user: Annotated[User, Depends(get_current_user)]) -> dict:
    """Return the current authenticated user (id, email). Use this to verify your Bearer token."""
    return {"id": current_user.id, "email": current_user.email}
