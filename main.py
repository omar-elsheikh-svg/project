import io
import logging
import uuid

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.ai_service import generate_executive_report
from app.auth import current_user
from app.billing import create_checkout_session, handle_webhook
from app.config import get_settings
from app.limits import ensure_premium, ensure_report_allowed, record_report_usage
from app.reports import insights_markdown, insights_pdf
from app.supabase_client import get_supabase
from project import calculate_all_insights, clean_df, features_finder

settings = get_settings()
logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Sales Intelligence API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Stripe-Signature"],
)

ALLOWED_SUFFIXES = {".csv", ".xlsx"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/me")
def profile(user: dict = Depends(current_user)) -> dict:
    result = (
        get_supabase()
        .table("profiles")
        .select("plan")
        .eq("id", user["id"])
        .maybe_single()
        .execute()
    )
    plan = str((result.data or {}).get("plan", "free")).lower()
    return {"user_id": user["id"], "plan": plan, "tier": plan}


@app.post("/datasets/analyze")
@limiter.limit("10/minute")
async def analyze_dataset(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
) -> dict:
    suffix = (
        "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    )
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415, detail="Only CSV and XLSX files are supported"
        )
    payload = await file.read()
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the upload limit")
    try:
        raw = (
            pd.read_csv(io.BytesIO(payload))
            if suffix == ".csv"
            else pd.read_excel(io.BytesIO(payload))
        )
        insights = calculate_all_insights(features_finder(clean_df(raw)))
    except (ValueError, OSError, pd.errors.ParserError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not analyze file: {exc}"
        ) from exc

    dataset_id = str(uuid.uuid4())
    get_supabase().table("datasets").insert(
        {
            "id": dataset_id,
            "user_id": user["id"],
            "filename": file.filename,
            "insights": insights,
        }
    ).execute()
    return {"dataset_id": dataset_id, "filename": file.filename, "insights": insights}


@app.post("/datasets/{dataset_id}/ai-report")
@limiter.limit("5/minute")
async def create_ai_report(
    request: Request, dataset_id: str, user: dict = Depends(current_user)
) -> dict:
    try:
        ensure_premium(user["id"])
        ensure_report_allowed(user["id"])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not verify report usage. Check that the profiles table is configured in Supabase.",
        ) from exc
    result = (
        get_supabase()
        .table("datasets")
        .select("insights")
        .eq("id", dataset_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        report = await generate_executive_report(result.data["insights"])
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The AI report service is temporarily unavailable. Check OPENROUTER_API_KEY and configured free models, then try again.",
        ) from exc
    try:
        get_supabase().table("reports").insert(
            {"dataset_id": dataset_id, "user_id": user["id"], "content": report}
        ).execute()
        record_report_usage(user["id"])
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="The report was generated but could not be saved. Check the Supabase reports table.",
        ) from exc
    return {"dataset_id": dataset_id, "report": report}


@app.get("/datasets/{dataset_id}/markdown")
def download_markdown(dataset_id: str, user: dict = Depends(current_user)) -> Response:
    ensure_premium(user["id"])
    result = (
        get_supabase()
        .table("datasets")
        .select("insights")
        .eq("id", dataset_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return Response(
        insights_markdown(result.data["insights"]),
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=report.md"},
    )


@app.get("/datasets/{dataset_id}/pdf")
def download_pdf(dataset_id: str, user: dict = Depends(current_user)) -> Response:
    ensure_premium(user["id"])
    result = (
        get_supabase()
        .table("datasets")
        .select("insights")
        .eq("id", dataset_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return Response(
        insights_pdf(result.data["insights"]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=report.pdf"},
    )


@app.post("/billing/checkout")
def checkout(user: dict = Depends(current_user)) -> dict:
    return {"checkout_url": create_checkout_session(user)}


@app.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict:
    try:
        handle_webhook(
            await request.body(), request.headers.get("stripe-signature", "")
        )
    except Exception as exc:
        logger.exception("Stripe webhook processing failed")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc
    return {"received": True}
