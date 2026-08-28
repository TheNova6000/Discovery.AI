from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Header, HTTPException

# Set only on a real deployment (Render), to the same Supabase project URL the
# frontend uses. Left unset for the local/VM hackathon demo, which then behaves
# exactly as before: every request is treated as one fixed local user, matching
# docs/PRD.md's original "solo user, no auth" scope.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
LOCAL_DEV_USER_ID = "local-dev"

# Verified against Supabase's own public keys (JWKS), not a shared secret —
# Supabase projects created since the "JWT Signing Keys" rollout sign access
# tokens asymmetrically (ES256 here, confirmed against a live token's header;
# some projects use RS256), so a static HS256 "JWT secret" can never verify
# them regardless of whether the secret itself is correct. Fetching the public
# key by `kid` from this endpoint is the correct approach for either signing
# scheme, and needs no secret at all — only the project's already-public URL.
_jwks_client: Optional["jwt.PyJWKClient"] = None


def _get_jwks_client() -> "jwt.PyJWKClient":
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client


async def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: resolves the caller's user id from a Supabase-issued
    access token's `sub` claim — that id is what scopes each user to their own
    sessions (see `get_store` in session.py). Rejects with 401 rather than
    silently falling back to a shared identity once auth is actually
    configured; a wrong/expired token must never be treated as "someone else's
    data is fine to show."
    """
    if not SUPABASE_URL:
        return LOCAL_DEV_USER_ID

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    return user_id
