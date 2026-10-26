# payment.py
"""Stripe checkout + webhook."""

import logging
import os

import stripe
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from auth import downgrade_subscription, get_current_user, set_stripe_customer_id, update_user_subscription
from config import PUBLIC_BASE_URL, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

logger = logging.getLogger(__name__)
stripe.api_key = STRIPE_SECRET_KEY

# price_type → (Stripe price id, tier it grants, checkout mode)
# Price ids can be overridden from the environment when you change prices in Stripe.
PLANS = {
    "premium_monthly": (
        os.getenv("STRIPE_PRICE_PREMIUM_MONTHLY", "price_1U6bkIF49k4gEmVB1tm8Vrq0"),
        "premium",
        "subscription",
    ),
    "ultimate_monthly": (
        os.getenv("STRIPE_PRICE_ULTIMATE_MONTHLY", "price_1TgVcYF49k4gEmVBkfUe13d6"),
        "ultimate",
        "subscription",
    ),
}

# Stripe subscription statuses that mean the user should lose paid access
ENDED_STATUSES = {"canceled", "unpaid", "incomplete_expired"}

router = APIRouter(prefix="/payments", tags=["payments"])


def _field(obj, key, default=None):
    """Read a field from a Stripe object or a plain dict."""
    try:
        value = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if value is None else value


@router.post("/create-checkout-session")
def create_checkout_session(data: dict = Body(...), current_user: dict = Depends(get_current_user)):
    price_type = data.get("price_type")
    if price_type not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid price type")
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments are not configured")

    price_id, _tier, mode = PLANS[price_type]
    try:
        customer_id = current_user.get("stripe_customer_id")
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user["email"],
                metadata={"user_id": str(current_user["id"])},
            )
            customer_id = customer.id
            set_stripe_customer_id(current_user["id"], customer_id)

        checkout = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode=mode,
            success_url=f"{PUBLIC_BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{PUBLIC_BASE_URL}/chat",
            client_reference_id=f"{current_user['id']}:{price_type}",
            metadata={"price_type": price_type, "user_id": str(current_user["id"])},
        )
        logger.info(f"✅ Checkout session created for user {current_user['id']} → {price_type}")
        return {"url": checkout.url}
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=502, detail="Payment service temporarily unavailable")


def _handle_checkout_completed(session) -> None:
    ref = _field(session, "client_reference_id", "")
    user_id_str, _, price_type = ref.partition(":")
    if not user_id_str.isdigit() or price_type not in PLANS:
        logger.warning(f"WEBHOOK: unrecognised client_reference_id {ref!r}")
        return
    if _field(session, "payment_status") not in ("paid", "no_payment_required"):
        logger.warning(f"WEBHOOK: checkout for user {user_id_str} not paid yet")
        return

    _price_id, tier, _mode = PLANS[price_type]
    if update_user_subscription(int(user_id_str), tier, _field(session, "subscription")):
        logger.info(f"✅ WEBHOOK: user {user_id_str} upgraded to {tier}")
    else:
        logger.error(f"❌ WEBHOOK: upgrade failed for user {user_id_str}")


def _handle_subscription_change(subscription, event_type: str) -> None:
    status = _field(subscription, "status", "")
    if event_type == "customer.subscription.deleted" or status in ENDED_STATUSES:
        downgrade_subscription(_field(subscription, "id"), status or "canceled")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook is not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.error(f"Webhook signature error: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = _field(event, "type")
    obj = _field(_field(event, "data", {}), "object", {})

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(obj)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        _handle_subscription_change(obj, event_type)

    return {"status": "success"}
