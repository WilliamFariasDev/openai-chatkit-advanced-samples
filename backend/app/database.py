"""Database connection pooling and utilities."""

from __future__ import annotations

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_db_pool() -> None:
    """Close the database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_user_id_from_auth_id(auth_user_id: str) -> int | None:
    """Get the public user ID from the Supabase auth user ID.

    Args:
        auth_user_id: The Supabase auth user ID (UUID)

    Returns:
        The public user ID (bigint) or None if not found
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM public.users
            WHERE auth_user_id = $1
            LIMIT 1
            """,
            auth_user_id,
        )
        return row["id"] if row else None
