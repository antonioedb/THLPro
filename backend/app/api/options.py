from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models import Asset, OptionSeries, OptionType, SystemSetting, User
from app.schemas.options import OptionSeriesOut, OptionSynchronizeRequest, SyncSummary
from app.services.strike_rules import resolve_series_by_strike
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
        asset_obj = (await db.execute(select(Asset).where(Asset.symbol == asset.upper()))).scalar_one_or_none()
        if asset_obj:
            stmt = stmt.where(OptionSeries.asset_id == asset_obj.id)
    stmt = stmt.order_by(OptionSeries.expiration_date, OptionSeries.strike)
    rows = (await db.execute(stmt)).scalars().all()
    return [OptionSeriesOut.model_validate(r) for r in rows]


@router.get("/search", response_model=list[OptionSeriesOut], summary="Busca séries por símbolo")
async def search_options(q: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[OptionSeriesOut]:
    rows = (await db.execute(select(OptionSeries).where(OptionSeries.option_symbol.ilike(f"%{q.upper()}%")))).scalars().all()
    return [OptionSeriesOut.model_validate(r) for r in rows]


@router.get("/by-expiration", response_model=list[OptionSeriesOut], summary="Lista séries por vencimento")
async def by_expiration(
    asset: str,
    expiration: date,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OptionSeriesOut]:
    asset_obj = (await db.execute(select(Asset).where(Asset.symbol == asset.upper()))).scalar_one_or_none()
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
    return [OptionSeriesOut.model_validate(r) for r in rows]


@router.get("/by-strike", summary="Resolve séries por strike com tolerância")
async def by_strike(
    asset: str,
    strike: Decimal,
    expiration_count: int = Query(default=6, ge=1, le=12),
    types: str = "CALL,PUT",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    asset_obj = (await db.execute(select(Asset).where(Asset.symbol == asset.upper()))).scalar_one_or_none()
    if not asset_obj:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")

    expiration_dates = (
        await db.execute(
            select(OptionSeries.expiration_date)
            .where(OptionSeries.asset_id == asset_obj.id, OptionSeries.active.is_(True))
            .group_by(OptionSeries.expiration_date)
            .order_by(OptionSeries.expiration_date.asc())
            .limit(expiration_count)
        )
    ).scalars().all()

    tol_row = (await db.execute(select(SystemSetting).where(SystemSetting.key == "strike_tolerance"))).scalar_one_or_none()
    tolerance = Decimal(str(tol_row.value.get("value", "0.50"))) if tol_row else Decimal("0.50")

    wanted_types = {x.strip().upper() for x in types.split(",")}
    result = []
    for exp in expiration_dates:
        for raw_type in [OptionType.CALL, OptionType.PUT]:
            if raw_type.value not in wanted_types:
                continue
            matched, applied = await resolve_series_by_strike(
                db,
                asset_id=asset_obj.id,
                option_type=raw_type,
                requested_strike=strike,
                expiration_date=exp,
                tolerance=tolerance,
            )
            if matched:
                result.append(
                    {
                        "expiration_date": exp,
                        "option_type": raw_type.value,
                        "requested_strike": strike,
                        "matched_strike": matched.strike,
                        "tolerance_applied": applied,
                        "option_symbol": matched.option_symbol,
                    }
                )
            else:
                result.append(
                    {
                        "expiration_date": exp,
                        "option_type": raw_type.value,
                        "requested_strike": strike,
                        "matched_strike": None,
                        "tolerance_applied": None,
                        "option_symbol": None,
                        "status": "N/D",
                    }
                )
    return {"asset": asset_obj.symbol, "items": result}


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

    summary = await sync_from_file(db, "/home/ubuntu/thlpro/backend/tests/fixtures/b3_series_sample.txt")
    return SyncSummary(**summary)
