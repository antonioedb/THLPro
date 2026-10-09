from datetime import datetime, timezone
UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, MeResponse, MessageResponse, TokenResponse
from app.services.log_service import log_event

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=TokenResponse, summary="Realiza login e retorna token JWT")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas.")

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await log_event(db, event_type="login", message="Login realizado com sucesso.", user_id=user.id)

    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        expires_in_seconds=settings.access_token_expire_hours * 3600,
    )


@router.post("/logout", response_model=MessageResponse, summary="Registra logout da sessão atual")
async def logout(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MessageResponse:
    await log_event(db, event_type="logout", message="Logout realizado.", user_id=current_user.id)
    return MessageResponse(message="Logout registrado com sucesso.")


@router.get("/me", response_model=MeResponse, summary="Retorna dados do usuário autenticado")
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse.model_validate(current_user)
