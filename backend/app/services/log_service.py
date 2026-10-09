from datetime import datetime, timezone
UTC = timezone.utc

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SynchronizationLog


async def log_event(
    db: AsyncSession,
    *,
    event_type: str,
    message: str,
    user_id: int | None = None,
    client_id: int | None = None,
    payload_summary: dict | None = None,
) -> None:
    db.add(
        SynchronizationLog(
            user_id=user_id,
            client_id=client_id,
            event_type=event_type,
            message=message,
            payload_summary=payload_summary,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
