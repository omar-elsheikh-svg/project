import stripe

from .config import get_settings
from .supabase_client import get_supabase


def create_checkout_session(user: dict) -> str:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=user.get("email"),
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.frontend_url}/?billing=success",
        cancel_url=f"{settings.frontend_url}/?billing=cancelled",
        metadata={"user_id": user["id"]},
    )
    return session.url


def handle_webhook(payload: bytes, signature: str) -> None:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    event = stripe.Webhook.construct_event(
        payload, signature, settings.stripe_webhook_secret
    )
    event_type = event["type"]
    subscription = event["data"]["object"]
    user_id = subscription.get("metadata", {}).get("user_id")
    if not user_id:
        return
    plan = (
        "premium"
        if event_type in {"checkout.session.completed", "customer.subscription.updated"}
        else "free"
    )
    get_supabase().table("profiles").update(
        {"plan": plan, "stripe_subscription_id": subscription.get("id")}
    ).eq("id", user_id).execute()
