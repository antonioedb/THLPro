from datetime import datetime, timezone
UTC = timezone.utc
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, hash_password, verify_password
from app.database import get_db
from app.models import Client, User, UserRole


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado.",
    )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", "0"))
    except Exception as exc:  # noqa: BLE001
        raise credentials_exception from exc

    user = await db.get(User, user_id)
    if not user or not user.active:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return current_user


async def get_client_from_api_key(
    db: AsyncSession = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Client:
    raw_key = x_api_key
    if not raw_key and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1]
    if not raw_key:
        raise HTTPException(status_code=401, detail="API key do cliente não informada.")

    result = await db.execute(select(Client))
    clients = result.scalars().all()
    matched = None
    for client in clients:
        if verify_password(raw_key, client.api_key_hash):
            matched = client
            break
    if not matched:
        raise HTTPException(status_code=401, detail="API key do cliente inválida.")

    matched.connected = True
    matched.last_seen_at = datetime.now(UTC)
    await db.commit()
    return matched


def hash_api_key(raw_key: str) -> str:
    return hash_password(raw_key)
