# auth.py - Full User Authentication with Safe Migrations
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, ExpiredSignatureError, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import sqlite3
import os
import logging

from config import JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger(__name__)
DB_PATH = os.path.abspath(os.getenv("DB_PATH", "isabella.db"))

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def register_user(email: str, password: str, full_name: str):
    email = email.lower().strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        # Safe migration: ensure full_name column exists
        c.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in c.fetchall()]
        
        if "full_name" not in columns:
            logger.info("Migrating: Adding full_name column to users table")
            c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

        hashed = get_password_hash(password)
        c.execute('''
            INSERT INTO users (email, hashed_password, full_name)
            VALUES (?, ?, ?)
        ''', (email, hashed, full_name))
        conn.commit()
        logger.info(f"✅ New user registered: {email}")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Email already exists: {email}")
        return False
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return False
    finally:
        conn.close()


def authenticate_user(email: str, password: str):
    email = email.lower().strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Select id, email, hashed_password, full_name
    c.execute("""
        SELECT id, email, hashed_password, full_name 
        FROM users 
        WHERE email = ?
    """, (email,))
    
    user = c.fetchone()
    conn.close()

    if not user:
        logger.info(f"Auth failed: No user found for {email}")
        return None

    # Correct index: hashed_password is at index 2
    if not verify_password(password, user[2]):
        logger.info(f"Auth failed: Wrong password for {email}")
        return None

    logger.info(f"✅ Auth success for {email}")
    return {
        "id": user[0],
        "email": user[1],
        "full_name": user[3] if len(user) > 3 else None
    }


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except:
        raise credentials_exception

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, full_name FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if user is None:
        raise credentials_exception
    return {"id": user[0], "email": user[1], "full_name": user[2] if len(user) > 2 else None}
