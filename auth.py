# auth.py - Full User Authentication + Profile
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, ExpiredSignatureError, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import sqlite3
import os
import logging
import json

from config import JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, ADMIN_TOKEN

logger = logging.getLogger(__name__)
DB_PATH = os.path.abspath(os.getenv("DB_PATH", "users.db"))

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


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
        hashed = get_password_hash(password)
        c.execute('''
            INSERT INTO users (email, hashed_password, full_name)
            VALUES (?, ?, ?)
        ''', (email, hashed, full_name))
        conn.commit()
        logger.info(f"New user registered: {email}")
        return True
    except sqlite3.IntegrityError:
        return False  # Email already exists
    finally:
        conn.close()


def authenticate_user(email: str, password: str):
    email = email.lower().strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, full_name FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    conn.close()

    if not user or not verify_password(password, user[2] if len(user) > 2 else ""):  # Adjust index if needed
        return None
    return {"id": user[0], "email": user[1], "full_name": user[2] if len(user) > 2 else None}


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
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
