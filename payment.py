# payment.py - Clean & Robust Version
import stripe
from fastapi import APIRouter, HTTPException, Request, Depends, Body
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import logging

from auth import get_current_user, update_user_subscription

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

logger = logging.getLogger(__name__)

# ============== PRICE CONFIG ==============
PRICE_IDS = {
    "pic_tease": "price_1T1f1cF49k4gEmVBLQ7Mu5xd",
    "premium_monthly": "price_1TgVcyF49k4gEmVBM7p27KwH",
    "ultimate_monthly": "price_1TgVcYF49k4gEmVBkfUe13d6",
}

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/create-checkout-session")
async def create_checkout_session(
    data: dict = Body(...),                    # ← This is the key change
    current_user: dict = Depends(get_current_user)
):
    price_type = data.get("price_type")
    
    if not price_type or price_type not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid price type")

    try:
        price_id = PRICE_IDS[price_type]
        is_subscription = "monthly" in price_type

        customer = stripe.Customer.create(
            email=current_user["email"],
            metadata={"user_id": str(current_user["id"])}
        )

        checkout = stripe.checkout.Session.create(
            customer=customer.id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription" if is_subscription else "payment",
            success_url="https://www.aurorasparq.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://www.aurorasparq.com/",
            metadata={
                "user_id": str(current_user["id"]),
                "price_type": price_type,
            }
        )

        logger.info(f"✅ Checkout session created for user {current_user['id']} → {price_type}")
        return {"url": checkout.url}

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=500, detail="Payment service temporarily unavailable")
    except Exception as e:
        logger.error(f"Checkout error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Webhook
@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logger.error(f"Webhook signature error: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # Get user_id from Customer (primary source)
        user_id_str = None
        customer_id = getattr(session, "customer", None)
        
        if customer_id:
            try:
                customer = stripe.Customer.retrieve(customer_id)
                cust_meta = getattr(customer, "metadata", None) or {}
                
                logger.info(f"WEBHOOK Customer metadata: {cust_meta}")

                if isinstance(cust_meta, dict):
                    user_id_str = cust_meta.get("user_id")
            except Exception as e:
                logger.warning(f"Customer error: {e}")

        # Get price_type from Session metadata
        price_type = None
        meta = getattr(session, "metadata", None) or {}
        if isinstance(meta, dict):
            price_type = meta.get("price_type")

        logger.info(f"WEBHOOK FINAL → user_id: {user_id_str}, price_type: {price_type}")

        if user_id_str and price_type:
            try:
                user_id = int(user_id_str)
                tier = "premium" if "premium" in str(price_type).lower() else "ultimate"

                success = update_user_subscription(user_id, tier, getattr(session, "subscription", None))
                if success:
                    logger.info(f"✅ WEBHOOK SUCCESS: User {user_id} upgraded to {tier}")
                else:
                    logger.error(f"❌ WEBHOOK failed for user {user_id}")
            except Exception as e:
                logger.error(f"Webhook error: {e}")
        else:
            logger.warning("WEBHOOK: Missing user_id or price_type after extraction")

    return {"status": "success"}
