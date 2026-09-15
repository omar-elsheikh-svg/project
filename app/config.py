from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# شحن متغيرات البيئة فوراً في الذاكرة
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_url: str = "http://localhost:8501"
    api_url: str = "http://localhost:8000"
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_id: str
    free_reports_per_month: int = 3
    max_upload_bytes: int = 10 * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_nested_delimiter="__", case_sensitive=False
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
