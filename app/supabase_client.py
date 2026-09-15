from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings


@lru_cache
def get_supabase() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_user_from_token(access_token: str) -> dict:
    """Validate a Supabase access token without trusting client-provided user IDs."""
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    response = client.auth.get_user(access_token)
    if not response or not response.user:
        raise ValueError("Invalid or expired access token")
    return {"id": response.user.id, "email": response.user.email}
