"""Authentication middleware and dependencies for Supabase JWT validation."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import get_user_id_from_auth_id
from .supabase_client import create_supabase_auth_client

security = HTTPBearer()


class AuthUser:
    """Authenticated user information from Supabase."""

    def __init__(
        self, user_id: str, email: str | None, raw: dict, public_user_id: int | None = None
    ):
        self.id = user_id
        self.email = email
        self.raw = raw
        self.public_user_id = public_user_id


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> AuthUser:
    """Validate JWT token from Supabase and return authenticated user.

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        AuthUser: Authenticated user information

    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = credentials.credentials

    supabase = create_supabase_auth_client()

    try:
        response = supabase.auth.get_user(token)
        user = response.user

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de autenticação inválido.",
            )

        # Get the public user ID from the database
        public_user_id = await get_user_id_from_auth_id(user.id)

        if not public_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado no banco de dados.",
            )

        return AuthUser(
            user_id=user.id,
            email=user.email,
            raw=user.model_dump() if hasattr(user, "model_dump") else dict(user),
            public_user_id=public_user_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Erro ao validar token: {str(e)}",
        ) from e


async def get_current_user_optional(
    request: Request,
) -> AuthUser | None:
    """Get current user if authenticated, otherwise return None.

    Useful for endpoints that can work with or without authentication.

    Args:
        request: FastAPI request object

    Returns:
        AuthUser | None: Authenticated user or None
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # Remove "Bearer " prefix

    supabase = create_supabase_auth_client()

    try:
        response = supabase.auth.get_user(token)
        user = response.user

        if not user:
            return None

        # Get the public user ID from the database
        public_user_id = await get_user_id_from_auth_id(user.id)

        return AuthUser(
            user_id=user.id,
            email=user.email,
            raw=user.model_dump() if hasattr(user, "model_dump") else dict(user),
            public_user_id=public_user_id,
        )

    except Exception:
        return None
