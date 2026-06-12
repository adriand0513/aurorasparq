# payment.py - Clean & Robust Version
import stripe
from fastapi import APIRouter, HTTPException, Request, Depends
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
    price_type: str,
    current_user: dict = Depends(get_current_user)
):
    if price_type not in PRICE_IDS:
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


# Success Page
@router.get("/success")
async def payment_success(session_id: str = None):
    if not session_id:
        return HTMLResponse("<h2>Payment Successful! Redirecting...</h2><script>setTimeout(() => window.location.href='/', 2000);</script>")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.payment_status == "paid" or session.status == "complete":
            user_id_str = session.metadata.get("user_id")
            price_type = session.metadata.get("price_type")
            
            if user_id_str and price_type:
                user_id = int(user_id_str)
                tier = "premium" if "premium" in price_type else "ultimate"
                update_user_subscription(user_id, tier, session.get("subscription"))
                logger.info(f"✅ Success page upgraded user {user_id} to {tier}")

        # Serve beautiful success page
        with open("static/success.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    except Exception as e:
        logger.error(f"Success page error: {e}")
        return HTMLResponse("""
            <h1 style="text-align:center;margin-top:100px;color:#c300ff;">
                Payment Successful!<br><br>
                Redirecting to chat...
            </h1>
            <script>setTimeout(() => window.location.href='/', 3000);</script>
        """)


# Webhook
@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id_str = session.get("metadata", {}).get("user_id")
        price_type = session.get("metadata", {}).get("price_type")

        if user_id_str and price_type:
            user_id = int(user_id_str)
            tier = "premium" if "premium" in price_type else "ultimate"
            update_user_subscription(user_id, tier, session.get("subscription"))
            logger.info(f"✅ Webhook upgraded user {user_id} to {tier}")

    return {"status": "success"}
