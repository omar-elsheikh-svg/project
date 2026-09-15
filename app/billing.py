import logging

import stripe

from .config import get_settings
from .supabase_client import get_supabase

logger = logging.getLogger(__name__)


def create_checkout_session(user: dict) -> str:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=user.get("email"),
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        subscription_data={"metadata": {"user_id": user["id"]}},
        success_url=f"{settings.frontend_url}/?billing=success",
        cancel_url=f"{settings.frontend_url}/?billing=cancelled",
        metadata={"user_id": user["id"]},
    )
    return session.url


def handle_webhook(payload: bytes, signature: str) -> None:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except Exception:
        logger.exception("Stripe webhook signature verification failed")
        raise

    event_type = event["type"]
    billing_object = event["data"]["object"]
    metadata = billing_object.get("metadata", {}) or {}
    user_id = metadata.get("user_id")
    if not user_id:
        logger.warning("Ignoring Stripe event %s without metadata.user_id", event_type)
        return

    if event_type not in {
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        logger.info("Ignoring unsupported Stripe event %s", event_type)
        return

    plan = (
        "premium"
        if event_type in {"checkout.session.completed", "customer.subscription.updated"}
        else "free"
    )
    subscription_id = billing_object.get("subscription") if event_type == "checkout.session.completed" else billing_object.get("id")
    try:
        result = (
            get_supabase()
            .table("profiles")
            .update({"plan": plan, "stripe_subscription_id": subscription_id})
            .eq("id", user_id)
            .execute()
        )
        if getattr(result, "error", None):
            raise RuntimeError(str(result.error))
    except Exception:
        logger.exception(
            "Failed to update profile plan for Stripe event %s and user %s",
            event_type,
            user_id,
        )
        raise

    logger.info("Updated user %s to %s after Stripe event %s", user_id, plan, event_type)
