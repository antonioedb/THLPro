from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.security import hash_password
from app.database import get_db
from app.models import User, UserPreference, UserRole
from app.schemas.auth import MessageResponse
from app.schemas.users import UserCreate, UserOut, UserPreferenceOut, UserPreferenceUpdate, UserUpdate

router = APIRouter(prefix="/users", tags=["Usuários"])


async def _get_or_create_user_preferences(db: AsyncSession, user_id: int) -> UserPreference:
    preferences = (await db.execute(select(UserPreference).where(UserPreference.user_id == user_id))).scalar_one_or_none()
    if preferences:
        return preferences

    preferences = UserPreference(user_id=user_id)
    db.add(preferences)
    await db.commit()
    await db.refresh(preferences)
    return preferences


@router.get("", response_model=list[UserOut], summary="Lista usuários (admin)")
async def list_users(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=UserOut, summary="Cria usuário (admin)")
async def create_user(payload: UserCreate, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> UserOut:
    if (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado.")
    role = UserRole.admin if payload.role == "admin" else UserRole.user
    user = User(name=payload.name, email=payload.email, password_hash=hash_password(payload.password), role=role, active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me/preferences", response_model=UserPreferenceOut, summary="Obtém preferências do usuário autenticado")
async def get_my_preferences(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserPreferenceOut:
    preferences = await _get_or_create_user_preferences(db, current_user.id)
    return UserPreferenceOut.model_validate(preferences)


@router.put("/me/preferences", response_model=UserPreferenceOut, summary="Atualiza preferências do usuário autenticado")
async def update_my_preferences(
    payload: UserPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferenceOut:
    preferences = await _get_or_create_user_preferences(db, current_user.id)

    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(preferences, field, value)

    await db.commit()
    await db.refresh(preferences)
    return UserPreferenceOut.model_validate(preferences)


@router.get("/{user_id}", response_model=UserOut, summary="Obtém usuário por ID (admin)")
async def get_user(user_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return UserOut.model_validate(user)


@router.put("/{user_id}", response_model=UserOut, summary="Atualiza usuário (admin)")
async def update_user(user_id: int, payload: UserUpdate, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if payload.name is not None:
        user.name = payload.name
    if payload.active is not None:
        user.active = payload.active
    if payload.role is not None:
        user.role = UserRole.admin if payload.role == "admin" else UserRole.user
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", response_model=MessageResponse, summary="Desativa usuário (admin)")
async def delete_user(user_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> MessageResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    user.active = False
    await db.commit()
    return MessageResponse(message="Usuário desativado com sucesso.")
