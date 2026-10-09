from datetime import datetime, timezone
UTC = timezone.utc

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["Saúde"])


@router.get("/health", summary="Healthcheck do backend")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    settings = get_settings()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": "ok" if db_ok else "erro",
        "utc_time": datetime.now(UTC).isoformat(),
    }
