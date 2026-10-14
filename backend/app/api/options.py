from datetime import date
from decimal import Decimal




from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession




from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models import Asset, OptionSeries, OptionType, SystemSetting, User
from app.schemas.options import OptionSeriesOut, OptionSynchronizeRequest, SyncSummary
from app.services.capture_demand import capture_demand_store
from app.services.strike_rules import resolve_series_by_strike
from app.services.websocket_manager import manager
import httpx




from app.services.sync_b3 import B3_SAMPLE_URL, sync_from_file, sync_from_lines




router = APIRouter(prefix="/options", tags=["Opções"])





@router.get("", response_model=list[OptionSeriesOut], summary="Lista séries de opções")
async def list_options(
    asset: str | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OptionSeriesOut]:
    stmt = select(OptionSeries)



    if asset:
        asset_obj = (
            await db.execute(select(Asset).where(Asset.symbol == asset.upper()))
        ).scalar_one_or_none()



        if asset_obj:
            stmt = stmt.where(OptionSeries.asset_id == asset_obj.id)



    stmt = stmt.order_by(OptionSeries.expiration_date, OptionSeries.strike)
    rows = (await db.execute(stmt)).scalars().all()



    return [OptionSeriesOut.model_validate(row) for row in rows]





@router.get("/search", response_model=list[OptionSeriesOut], summary="Busca séries por símbolo")
async def search_options(
    q: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OptionSeriesOut]:
    rows = (
        await db.execute(
            select(OptionSeries).where(
                OptionSeries.option_symbol.ilike(f"%{q.upper()}%")
            )
        )
    ).scalars().all()



    return [OptionSeriesOut.model_validate(row) for row in rows]





@router.get("/by-expiration", response_model=list[OptionSeriesOut], summary="Lista séries por vencimento")
async def by_expiration(
    asset: str,
    expiration: date,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OptionSeriesOut]:
    asset_obj = (
        await db.execute(select(Asset).where(Asset.symbol == asset.upper()))
    ).scalar_one_or_none()



    if not asset_obj:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")



    rows = (
        await db.execute(
            select(OptionSeries)
            .where(
                OptionSeries.asset_id == asset_obj.id,
                OptionSeries.expiration_date == expiration,
                OptionSeries.active.is_(True),
            )
            .order_by(OptionSeries.option_type, OptionSeries.strike)
        )
    ).scalars().all()



    return [OptionSeriesOut.model_validate(row) for row in rows]





async def get_monthly_expiration_dates(
    db: AsyncSession,
    asset_id: int,
    limit: int,
) -> list[date]:
    """
    Seleciona um vencimento mensal por mês.



    Para cada mês, escolhe o dia com o maior número de séries ativas.
    Normalmente esse é o vencimento mensal, e não os vencimentos semanais.
    """
    rows = (
        await db.execute(
            select(
                OptionSeries.expiration_date,
                func.count(OptionSeries.id).label("series_count"),
            )
            .where(
                OptionSeries.asset_id == asset_id,
                OptionSeries.active.is_(True),
            )
            .group_by(OptionSeries.expiration_date)
            .order_by(OptionSeries.expiration_date.asc())
        )
    ).all()



    monthly: dict[tuple[int, int], tuple[date, int]] = {}



    for expiration_date, series_count in rows:
        key = (expiration_date.year, expiration_date.month)
        current = monthly.get(key)



        if current is None or series_count > current[1]:
            monthly[key] = (expiration_date, series_count)



    selected = [
        item[0]
        for item in sorted(monthly.values(), key=lambda item: item[0])
    ]



    return selected[:limit]





@router.get("/by-strike", summary="Resolve séries mensais por strike com tolerância")
async def by_strike(
    asset: str,
    strike: Decimal,
    expiration_count: int = Query(default=6, ge=1, le=12),
    types: str = "CALL,PUT",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    asset_obj = (
        await db.execute(select(Asset).where(Asset.symbol == asset.upper()))
    ).scalar_one_or_none()



    if not asset_obj:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")




    expiration_dates = await get_monthly_expiration_dates(
        db,
        asset_obj.id,
        expiration_count,
    )




    tol_row = (
        await db.execute(
            select(SystemSetting).where(SystemSetting.key == "strike_tolerance")
        )
    ).scalar_one_or_none()



    tolerance = (
        Decimal(str(tol_row.value.get("value", "0.50")))
        if tol_row
        else Decimal("0.50")
    )




    wanted_types = {item.strip().upper() for item in types.split(",")}



    result = []



    for expiration_date in expiration_dates:
        for option_type in [OptionType.CALL, OptionType.PUT]:
            if option_type.value not in wanted_types:
                continue



            matched, applied = await resolve_series_by_strike(
                db,
                asset_id=asset_obj.id,
                option_type=option_type,
                requested_strike=strike,
                expiration_date=expiration_date,
                tolerance=tolerance,
            )



            if matched:
                result.append(
                    {
                        "expiration_date": expiration_date,
                        "option_type": option_type.value,
                        "requested_strike": strike,
                        "matched_strike": matched.strike,
                        "tolerance_applied": applied,
                        "option_symbol": matched.option_symbol,
                    }
                )
            else:
                result.append(
                    {
                        "expiration_date": expiration_date,
                        "option_type": option_type.value,
                        "requested_strike": strike,
                        "matched_strike": None,
                        "tolerance_applied": None,
                        "option_symbol": None,
                        "status": "N/D",
                    }
                )



    return {
        "asset": asset_obj.symbol,
        "items": result,
    }





@router.post(
    "/capture/subscribe-strike",
    summary="Solicita aos clientes RTD a captura das opções do strike selecionado",
)
async def subscribe_strike_capture(
    payload: dict,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Resolve as séries mensais do ativo e strike selecionados no frontend
    e solicita aos clientes RTD que substituam a captura atual apenas
    pelas opções encontradas.



    Payload esperado:
    {
        "asset": "PETR4",
        "strike": "40.00",
        "expiration_count": 6,
        "types": "CALL,PUT"
    }
    """
    asset_symbol = str(payload.get("asset", "")).strip().upper()
    strike_raw = payload.get("strike")
    expiration_count = int(payload.get("expiration_count", 6))
    types_raw = str(payload.get("types", "CALL,PUT"))



    if not asset_symbol:
        raise HTTPException(
            status_code=422,
            detail="O campo 'asset' é obrigatório.",
        )



    try:
        strike = Decimal(str(strike_raw))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="O campo 'strike' deve ser um número válido.",
        ) from exc



    expiration_count = max(1, min(expiration_count, 12))



    asset_obj = (
        await db.execute(
            select(Asset).where(Asset.symbol == asset_symbol)
        )
    ).scalar_one_or_none()



    if not asset_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Ativo {asset_symbol} não encontrado.",
        )



    expiration_dates = await get_monthly_expiration_dates(
        db,
        asset_obj.id,
        expiration_count,
    )



    tol_row = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.key == "strike_tolerance"
            )
        )
    ).scalar_one_or_none()



    tolerance = (
        Decimal(str(tol_row.value.get("value", "0.50")))
        if tol_row
        else Decimal("0.50")
    )



    wanted_types = {
        item.strip().upper()
        for item in types_raw.split(",")
        if item.strip()
    }



    if not wanted_types:
        wanted_types = {"CALL", "PUT"}



    selected_series: list[OptionSeries] = []



    for expiration_date in expiration_dates:
        for option_type in [OptionType.CALL, OptionType.PUT]:
            if option_type.value not in wanted_types:
                continue



            matched, _applied = await resolve_series_by_strike(
                db,
                asset_id=asset_obj.id,
                option_type=option_type,
                requested_strike=strike,
                expiration_date=expiration_date,
                tolerance=tolerance,
            )



            if matched:
                selected_series.append(matched)



    assets_payload = [
        {
            "symbol": asset_obj.symbol,
            "name": asset_obj.name,
            "tick_min": str(asset_obj.tick_min),
            "strike_interval": str(asset_obj.strike_interval),
            "rtd_identifier_pattern": asset_obj.rtd_identifier_pattern,
        }
    ]



    series_payload = [
        {
            "id": series.id,
            "option_symbol": series.option_symbol,
            "asset_id": series.asset_id,
            "option_type": series.option_type.value,
            "strike": str(series.strike),
            "expiration_date": series.expiration_date.isoformat(),
            "rtd_symbol": series.option_symbol,
        }
        for series in selected_series
    ]



    capture_payload = {
        "asset": asset_obj.symbol,
        "strike": str(strike),
        "assets": assets_payload,
        "active_series": series_payload,
    }



    capture_demand_store.set(capture_payload)



    await manager.broadcast(
        {
            "type": "capture_config",
            "data": capture_payload,
        }
    )



    return {
        "asset": asset_obj.symbol,
        "strike": str(strike),
        "expiration_count": expiration_count,
        "requested_series": len(series_payload),
        "series": series_payload,
        "message": (
            "Captura sob demanda registrada e comando enviado aos "
            "clientes RTD conectados."
        ),
    }





@router.post("/synchronize", response_model=SyncSummary, summary="Sincroniza séries de opções (admin)")
async def synchronize(
    payload: OptionSynchronizeRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SyncSummary:
    if payload.source == "b3":
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(B3_SAMPLE_URL)
                response.raise_for_status()



            lines = response.text.splitlines()



            summary = await sync_from_lines(db, lines, source="B3")



            return SyncSummary(**summary)



        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=(
                    "Não foi possível baixar o arquivo público da B3 neste ambiente. "
                    "Use sincronização por upload manual e verifique conectividade/URL no runbook."
                ),
            ) from exc




    summary = await sync_from_file(db, "data/series_autorizadas.txt")



    return SyncSummary(**summary)