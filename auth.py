# auth.py
"""
Accounts and login.

Security rules:
- No "bypass mode". If the database is down, login and protected routes
  fail with 503 instead of handing out fake premium accounts.
- The subscription tier always comes from the database, never from the
  token, and defaults to "free".
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET
from database import DatabaseUnavailable, db_cursor

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

MIN_PASSWORD_LENGTH = 8


def _service_unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service temporarily unavailable")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verify error: {e}")
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _row_to_user(row) -> dict:
    return {
        "id": row[0],
        "email": row[1],
        "full_name": row[2],
        "subscription_tier": (row[3] or "free").lower(),
    }


def register_user(email: str, password: str, full_name: str = "") -> bool:
    """True if created, False if the email is taken. Raises 503 if the DB is down."""
    email = email.lower().strip()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO users (email, hashed_password, full_name) VALUES (%s, %s, %s)",
                (email, get_password_hash(password), full_name),
            )
        logger.info(f"✅ Registered user {email}")
        return True
    except psycopg2.errors.UniqueViolation:
        return False
    except DatabaseUnavailable:
        raise _service_unavailable()


def authenticate_user(email: str, password: str) -> Optional[dict]:
    email = email.lower().strip()
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, subscription_tier, hashed_password FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    except DatabaseUnavailable:
        raise _service_unavailable()

    if row is None or not verify_password(password, row[4]):
        return None
    return _row_to_user(row)


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, email, full_name, subscription_tier, stripe_customer_id FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    user = _row_to_user(row)
    user["stripe_customer_id"] = row[4]
    return user


def set_stripe_customer_id(user_id: int, customer_id: str) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s", (customer_id, user_id))


def update_user_subscription(
    user_id: int,
    tier: str,
    stripe_subscription_id: Optional[str] = None,
    status: str = "active",
) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_tier = %s,
                    stripe_subscription_id = %s,
                    subscription_status = %s,
                    subscription_expires_at = CURRENT_TIMESTAMP + INTERVAL '1 month'
                WHERE id = %s
                """,
                (tier, stripe_subscription_id, status, user_id),
            )
            updated = cur.rowcount
        logger.info(f"✅ Subscription for user {user_id} set to {tier} ({status})")
        return updated == 1
    except Exception as e:
        logger.error(f"Subscription update error: {e}")
        return False


def downgrade_subscription(stripe_subscription_id: str, status: str) -> bool:
    """Drop a user back to free when Stripe ends or suspends their subscription."""
    if not stripe_subscription_id:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_tier = 'free', subscription_status = %s
                WHERE stripe_subscription_id = %s
                """,
                (status, stripe_subscription_id),
            )
            updated = cur.rowcount
        logger.info(f"⬇️ Subscription {stripe_subscription_id} → free ({status}), rows={updated}")
        return updated > 0
    except Exception as e:
        logger.error(f"Subscription downgrade error: {e}")
        return False


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

    try:
        user = get_user_by_id(user_id)
    except DatabaseUnavailable:
        raise _service_unavailable()

    if user is None:
        raise credentials_exception
    return user
