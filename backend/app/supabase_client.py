"""Supabase client factory for authentication and service operations."""

from __future__ import annotations

from supabase import Client, create_client

from .config import settings


def create_supabase_auth_client() -> Client:
    """Create a Supabase client for public authentication operations.

    Uses the anon key for user authentication and public operations.
    """
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def create_supabase_service_client() -> Client | None:
    """Create a Supabase client with service role privileges.

    Uses the service role key for admin operations. Returns None if not configured.
    """
    if not settings.supabase_service_role_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
