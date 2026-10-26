from unittest import mock

from conftest import register_and_login


def tier_of(user_id):
    import database
    with database.db_cursor() as cur:
        cur.execute("SELECT subscription_tier, subscription_status FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def send_event(client, event):
    import payment
    with mock.patch.object(payment.stripe.Webhook, "construct_event", return_value=event):
        return client.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})


def test_bad_signature_rejected(client):
    r = client.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "bad"})
    assert r.status_code == 400


def test_checkout_upgrade_then_cancel(client):
    _, user = register_and_login(client)
    uid = user["id"]
    paid = {"type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": f"{uid}:premium_monthly", "payment_status": "paid", "subscription": "sub_123"}}}
    assert send_event(client, paid).status_code == 200
    assert tier_of(uid) == ("premium", "active")

    cancelled = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_123", "status": "canceled"}}}
    send_event(client, cancelled)
    assert tier_of(uid) == ("free", "canceled")


def test_unknown_product_grants_nothing(client):
    """Old code gave 'ultimate' to anyone who bought the one-off pic_tease."""
    _, user = register_and_login(client)
    event = {"type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": f"{user['id']}:pic_tease", "payment_status": "paid"}}}
    send_event(client, event)
    assert tier_of(user["id"])[0] == "free"


def test_unpaid_checkout_grants_nothing(client):
    _, user = register_and_login(client)
    event = {"type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": f"{user['id']}:premium_monthly", "payment_status": "unpaid"}}}
    send_event(client, event)
    assert tier_of(user["id"])[0] == "free"


def test_checkout_reuses_stripe_customer(client):
    import payment
    headers, user = register_and_login(client)
    with mock.patch.object(payment.stripe.Customer, "create", return_value=mock.Mock(id="cus_1")) as create, \
         mock.patch.object(payment.stripe.checkout.Session, "create", return_value=mock.Mock(url="https://stripe/x")) as session:
        for _ in range(2):
            r = client.post("/payments/create-checkout-session", json={"price_type": "premium_monthly"}, headers=headers)
            assert r.json() == {"url": "https://stripe/x"}
    assert create.call_count == 1
    assert session.call_args.kwargs["success_url"].startswith("https://www.aurorasparq.com/success")
    assert client.post("/payments/create-checkout-session", json={"price_type": "pic_tease"}, headers=headers).status_code == 400
