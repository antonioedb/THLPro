from datetime import datetime, timedelta, timezone
UTC = timezone.utc
from secrets import token_urlsafe
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, role: str, expires_hours: int | None = None) -> str:
    exp_hours = expires_hours or settings.access_token_expire_hours
    expire = datetime.now(UTC) + timedelta(hours=exp_hours)
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def create_client_api_key() -> str:
    return f"thl_{token_urlsafe(32)}"
