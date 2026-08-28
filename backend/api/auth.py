from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Header, HTTPException

# Set only on a real deployment (Render, from the Supabase project's Settings ->
# API -> JWT Secret). Left unset for the local/VM hackathon demo, which then
# behaves exactly as before: every request is treated as one fixed local user,
# matching docs/PRD.md's original "solo user, no auth" scope. This means turning
# auth on/off is a single env var, not a code branch anyone has to remember to
# flip back.
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
LOCAL_DEV_USER_ID = "local-dev"


async def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: resolves the caller's user id.

    Supabase's Google-login flow issues a standard HS256 JWT (signed with the
    project's JWT Secret) whose `sub` claim is the user's stable Supabase user
    id — that id is what scopes each user to their own sessions (see
    `get_store` in session.py). Rejects with 401 rather than silently falling
    back to a shared identity once auth is actually configured; a wrong/expired
    token must never be treated as "someone else's data is fine to show."
    """
    if not SUPABASE_JWT_SECRET:
        return LOCAL_DEV_USER_ID

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    return user_id
