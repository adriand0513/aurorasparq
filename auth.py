# auth.py - Clean PostgreSQL Version
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import psycopg2
import logging
from config import JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, DATABASE_URL

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.warning(f"⚠️ PostgreSQL connection failed (local testing mode): {e}")
        return None


def ensure_users_table():
    """Create users table if it doesn't exist (safe for local testing)"""
    conn = get_db_connection()
    
    # If database is not available, skip table creation (local testing mode)
    if conn is None:
        logger.warning("⚠️ Skipping users table creation - PostgreSQL not available")
        return
    
    cur = None
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subscription_tier TEXT DEFAULT 'free',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                subscription_status TEXT DEFAULT 'inactive',
                subscription_expires_at TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("✅ Users table ensured in PostgreSQL")
    except Exception as e:
        logger.error(f"Table creation error: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


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


def register_user(email: str, password: str, full_name: str = "") -> bool:
    email = email.lower().strip()

    try:
        ensure_users_table()
    except Exception as e:
        logger.warning(f"Could not ensure users table (DB may be unavailable): {e}")

    conn = get_db_connection()

    # If database is not available, allow registration for local testing
    if conn is None:
        logger.warning(f"⚠️ Database unavailable — allowing registration for local testing: {email}")
        return True

    cur = conn.cursor()
    try:
        hashed = get_password_hash(password)
        cur.execute('''
            INSERT INTO users (email, hashed_password, full_name)
            VALUES (%s, %s, %s)
        ''', (email, hashed, full_name))
        conn.commit()
        logger.info(f"✅ Registered: {email}")
        return True
    except psycopg2.errors.UniqueViolation:
        logger.warning(f"Email already exists: {email}")
        return False
    except Exception as e:
        logger.error(f"Register error: {e}")
        return False
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        if conn:
            conn.close()

def authenticate_user(email: str, password: str):
    email = email.lower().strip()

    conn = get_db_connection()

    # === BYPASS MODE (Local Testing) ===
    if conn is None:
        logger.warning(f"⚠️ [BYPASS] Database unavailable — allowing login for testing: {email}")
        return {
            "id": 999,                    # Fake user ID
            "email": email,
            "full_name": email.split("@")[0].title(),
            "subscription_tier": "premium"   # Give Premium so you can test everything
        }

    cur = None
    try:
        ensure_users_table()

        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, full_name, hashed_password, subscription_tier 
            FROM users 
            WHERE email = %s
        """, (email,))
        
        user = cur.fetchone()

        if user is None:
            return None

        if verify_password(password, user[3]):
            return {
                "id": user[0],
                "email": user[1],
                "full_name": user[2],
                "subscription_tier": user[4] if len(user) > 4 else "free"
            }
        else:
            return None

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def update_user_subscription(user_id: int, tier: str, stripe_subscription_id: str = None, status: str = "active"):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('''
            UPDATE users 
            SET subscription_tier = %s,
                stripe_subscription_id = %s,
                subscription_status = %s,
                subscription_expires_at = CURRENT_TIMESTAMP + INTERVAL '1 month'
            WHERE id = %s
        ''', (tier, stripe_subscription_id, status, user_id))
        conn.commit()
        logger.info(f"✅ Subscription updated for user {user_id} to {tier}")
        return True
    except Exception as e:
        logger.error(f"Subscription update error: {e}")
        return False
    finally:
        cur.close()
        conn.close()


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
        email = payload.get("email")
        full_name = payload.get("full_name", "")
        tier = payload.get("subscription_tier", "premium")
    except Exception:
        raise credentials_exception

    conn = get_db_connection()

    # === BYPASS MODE (when database is unavailable) ===
    if conn is None:
        logger.warning("⚠️ [BYPASS] Using token data for get_current_user (no DB)")
        return {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "subscription_tier": tier
        }

    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, full_name, subscription_tier 
            FROM users 
            WHERE id = %s
        """, (user_id,))
        
        user = cur.fetchone()
        
        if user is None:
            # User not in DB but token is valid → still allow (bypass mode)
            return {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "subscription_tier": tier
            }

        return {
            "id": user[0],
            "email": user[1],
            "full_name": user[2],
            "subscription_tier": user[3] if user[3] else "premium"
        }

    except Exception as e:
        logger.error(f"get_current_user error: {e}")
        # Fallback to token data if something goes wrong
        return {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "subscription_tier": tier
        }
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# Ensure table on import
# ensure_users_table()