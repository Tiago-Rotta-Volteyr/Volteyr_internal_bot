"""
FastAPI dependencies: authentication (Supabase JWT).
Supports two modes:
- SUPABASE_JWT_SECRET set: verify JWT locally (fast, no network).
- SUPABASE_URL + SUPABASE_KEY set: verify via Supabase Auth API (GET /auth/v1/user).
"""
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import SUPABASE_JWT_SECRET, SUPABASE_KEY, SUPABASE_URL

HTTPBearerScheme = HTTPBearer(auto_error=False)


@dataclass
class User:
    """Authenticated user from JWT (Supabase auth.users)."""

    id: str
    email: str


async def _verify_via_supabase_api(token: str) -> User:
    """Verify token by calling Supabase Auth API (no JWT Secret needed)."""
    import httpx

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPABASE_URL and SUPABASE_KEY are required when SUPABASE_JWT_SECRET is not set",
        )
    url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/user"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_KEY,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    data = resp.json()
    user_id = data.get("id")
    email = (data.get("email") or "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user id",
        )
    return User(id=str(user_id), email=email)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearerScheme),
    ],
) -> User:
    """
    Extract Bearer token from Authorization header, verify via Supabase
    (local JWT decode if SUPABASE_JWT_SECRET is set, else Auth API),
    and return User (id, email). Raises 401 if missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
            headers={"WWW-Authenticate": 'Bearer realm="auth_required"'},
        )

    token = credentials.credentials

    if not SUPABASE_JWT_SECRET and (not SUPABASE_URL or not SUPABASE_KEY):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure SUPABASE_URL + SUPABASE_KEY (anon or service), or SUPABASE_JWT_SECRET for auth",
        )

    # Mode 1: local JWT verification (no network, needs JWT Secret from dashboard)
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                audience="authenticated",
                algorithms=["HS256"],
            )
            sub = payload.get("sub")
            email = (payload.get("email") or "").strip()
            if not sub:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token missing subject (sub)",
                )
            return User(id=str(sub), email=email)
        except HTTPException:
            raise
        except jwt.PyJWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from e

    # Mode 2: verify via Supabase Auth API (uses SUPABASE_URL + SUPABASE_KEY)
    return await _verify_via_supabase_api(token)
