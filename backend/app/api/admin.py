from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal



from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession



from app.core.deps import require_admin
from app.database import get_db
from app.models import Asset, AssetQuote, OptionSeries, SynchronizationLog, SystemSetting, User



router = APIRouter(prefix="/admin", tags=["Administração"])




PROTECTED_ASSET_SYMBOLS = {"ABEV3", "BOVA11"}




@router.get("/logs", summary="Consulta logs administrativos")
async def get_logs(
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(SynchronizationLog)
    if event_type:
        stmt = stmt.where(SynchronizationLog.event_type == event_type)
    stmt = stmt.order_by(desc(SynchronizationLog.created_at)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "event_type": r.event_type,
            "message": r.message,
            "payload_summary": r.payload_summary,
            "client_id": r.client_id,
            "user_id": r.user_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]




@router.get("/settings", summary="Lista configurações do sistema")
async def get_settings(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(SystemSetting).order_by(SystemSetting.key))).scalars().all()
    return [{"key": r.key, "value": r.value, "description": r.description, "updated_at": r.updated_at} for r in rows]




@router.post("/settings/{key}", summary="Atualiza configuração do sistema")
async def update_setting(key: str, value: dict, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if not row:
        row = SystemSetting(key=key, value=value, description=f"Configuração {key}", updated_at=datetime.now(UTC))
        db.add(row)
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)
    await db.commit()
    return {"message": "Configuração atualizada com sucesso."}




@router.get(
    "/assets/generics",
    summary="Lista ativos que serão removidos na limpeza",
)
async def list_generic_assets(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            select(
                Asset.id,
                Asset.symbol,
                Asset.name,
                Asset.enabled,
                func.count(OptionSeries.id).label("series_count"),
            )
            .outerjoin(
                OptionSeries,
                OptionSeries.asset_id == Asset.id,
            )
            .group_by(
                Asset.id,
                Asset.symbol,
                Asset.name,
                Asset.enabled,
            )
            .order_by(Asset.symbol)
        )
    ).all()


    return [
        {
            "id": asset_id,
            "symbol": symbol,
            "name": name,
            "enabled": enabled,
            "series_count": int(series_count),
            "protected": symbol in PROTECTED_ASSET_SYMBOLS,
        }
        for asset_id, symbol, name, enabled, series_count in rows
        if symbol not in PROTECTED_ASSET_SYMBOLS
    ]




@router.post(
    "/assets/cleanup-generics",
    summary="Remove todos os ativos exceto ABEV3 e BOVA11",
)
async def cleanup_generic_assets(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(Asset).where(
                Asset.symbol.notin_(PROTECTED_ASSET_SYMBOLS)
            )
        )
    ).scalars().all()


    removed: list[str] = []


    for asset in rows:
        removed.append(asset.symbol)
        await db.delete(asset)


    await db.commit()


    preserved = sorted(PROTECTED_ASSET_SYMBOLS)


    return {
        "removed": removed,
        "removed_count": len(removed),
        "preserved": preserved,
        "message": (
            "Limpeza concluída. Todos os ativos fora da lista protegida "
            "foram removidos, incluindo suas séries e dados dependentes. "
            "ABEV3 e BOVA11 foram preservados."
        ),
    }




@router.post("/simulation/generate", summary="Gera cotações simuladas para testes")
async def generate_simulation(asset: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    sim = (await db.execute(select(SystemSetting).where(SystemSetting.key == "simulation_mode"))).scalar_one_or_none()
    enabled = bool(sim and sim.value.get("value") is True)
    if not enabled:
        raise HTTPException(status_code=400, detail="Modo simulação está desativado.")


    asset_obj = (await db.execute(select(Asset).where(Asset.symbol == asset.upper()))).scalar_one_or_none()
    if not asset_obj:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")


    db.add(
        AssetQuote(
            asset_id=asset_obj.id,
            last_price=Decimal("100.00"),
            quote_timestamp=datetime.now(UTC),
            received_at=datetime.now(UTC),
            source="SIMULATED",
            data_status="OK",
        )
    )
    await db.commit()
    return {"message": "Dados simulados de teste gerados.", "badge": "dados simulados"}