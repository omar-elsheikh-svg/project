from datetime import datetime, timezone

from fastapi import HTTPException

from .config import get_settings
from .supabase_client import get_supabase


def normalize_plan(plan: object) -> str:
    value = " ".join(str(plan or "free").strip().lower().split())
    return "premium" if value in {"premium", "premium plan"} else "free"


def is_premium_plan(plan: object) -> bool:
    return normalize_plan(plan) == "premium"


def _profile(user_id: str) -> dict:
    result = (
        get_supabase()
        .table("profiles")
        .select("plan, reports_this_month, usage_month")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data or {}


def ensure_premium(user_id: str) -> None:
    if not is_premium_plan(_profile(user_id).get("plan")):
        raise HTTPException(status_code=402, detail="Premium subscription required")


def ensure_report_allowed(user_id: str) -> None:
    """Enforce the free plan in the database; never rely on a frontend counter."""
    settings = get_settings()
    profile = _profile(user_id)
    if not profile:
        get_supabase().table("profiles").upsert({"id": user_id}).execute()
        profile = {"plan": "free", "reports_this_month": 0}
    if is_premium_plan(profile.get("plan")):
        return
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    count = (
        profile.get("reports_this_month", 0)
        if profile.get("usage_month") == month
        else 0
    )
    if count >= settings.free_reports_per_month:
        raise HTTPException(status_code=402, detail="Monthly free report limit reached")


def record_report_usage(user_id: str) -> None:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    get_supabase().rpc(
        "increment_report_usage", {"profile_id": user_id, "month_key": month}
    ).execute()
