from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models import Asset, AssetQuote, OptionSeries, User
from app.schemas.assets import AssetCreate, AssetOut, AssetUpdate, StrikeListResponse
from app.schemas.auth import MessageResponse
from app.schemas.quotes import AssetQuoteIn
from app.services.strike_rules import get_strikes_in_range

router = APIRouter(prefix="/assets", tags=["Ativos"])


async def _get_asset_by_ref(db: AsyncSession, ref: str) -> Asset:
    asset = None
    if ref.isdigit():
        asset = await db.get(Asset, int(ref))
    if not asset:
        asset = (await db.execute(select(Asset).where(Asset.symbol == ref.upper()))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    return asset


@router.get("", response_model=list[AssetOut], summary="Lista ativos")
async def list_assets(
    enabled: bool | None = Query(default=None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AssetOut]:
    stmt = select(Asset).order_by(Asset.symbol)
    if enabled is not None:
        stmt = stmt.where(Asset.enabled == enabled)
    rows = (await db.execute(stmt)).scalars().all()
    return [AssetOut.model_validate(x) for x in rows]


@router.post("", response_model=AssetOut, summary="Cria ativo (admin)")
async def create_asset(payload: AssetCreate, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> AssetOut:
    if (await db.execute(select(Asset).where(Asset.symbol == payload.symbol.upper()))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ativo já cadastrado.")
    item = Asset(**payload.model_dump())
    item.symbol = item.symbol.upper()
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return AssetOut.model_validate(item)


@router.get("/{ref}", response_model=AssetOut, summary="Busca ativo por ID ou símbolo")
async def get_asset(ref: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AssetOut:
    asset = await _get_asset_by_ref(db, ref)
    return AssetOut.model_validate(asset)


@router.put("/{ref}", response_model=AssetOut, summary="Atualiza ativo (admin)")
async def update_asset(ref: str, payload: AssetUpdate, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> AssetOut:
    asset = await _get_asset_by_ref(db, ref)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(asset, key, value)
    await db.commit()
    await db.refresh(asset)
    return AssetOut.model_validate(asset)


@router.delete("/{ref}", response_model=MessageResponse, summary="Desativa ativo (admin)")
async def delete_asset(ref: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> MessageResponse:
    asset = await _get_asset_by_ref(db, ref)
    asset.enabled = False
    await db.commit()
    return MessageResponse(message="Ativo desativado com sucesso.")


@router.post("/quotes", summary="Recebe cotações do ativo-base")
async def post_asset_quotes(payload: list[AssetQuoteIn], _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    accepted = 0
    rejected = []
    for idx, row in enumerate(payload):
        symbol = row.asset.upper()
        asset = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
        if not asset:
            rejected.append({"index": idx, "reason": "Ativo não cadastrado."})
            continue
        item = AssetQuote(
            asset_id=asset.id,
            last_price=Decimal(row.last_price),
            variation_points=Decimal(row.variation_points) if row.variation_points is not None else None,
            variation_pct=Decimal(row.variation_pct) if row.variation_pct is not None else None,
            high=Decimal(row.high) if row.high is not None else None,
            low=Decimal(row.low) if row.low is not None else None,
            quote_timestamp=row.quote_timestamp,
            received_at=datetime.now(UTC),
            source=row.source,
            data_status=row.data_status,
        )
        db.add(item)
        accepted += 1
    await db.commit()
    return {"accepted": accepted, "rejected": rejected}


@router.get("/{symbol}/spot", summary="Retorna última cotação do ativo-base")
async def get_spot(symbol: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    asset = await _get_asset_by_ref(db, symbol)
    quote = (
        await db.execute(
            select(AssetQuote)
            .where(AssetQuote.asset_id == asset.id)
            .order_by(AssetQuote.quote_timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not quote:
        return {"asset": asset.symbol, "spot_price": None, "data_status": "NA", "message": "N/D"}
    return {
        "asset": asset.symbol,
        "spot_price": quote.last_price,
        "quote_timestamp": quote.quote_timestamp,
        "received_at": quote.received_at,
        "data_status": quote.data_status,
    }


@router.get("/{symbol}/strikes", response_model=StrikeListResponse, summary="Lista strikes ativos dentro da faixa configurada")
@router.get("/{symbol}/strikes/range", response_model=StrikeListResponse, summary="Lista strikes ativos dentro da faixa configurada")
async def get_strikes(symbol: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StrikeListResponse:
    asset = await _get_asset_by_ref(db, symbol)
    last_quote = (
        await db.execute(
            select(AssetQuote)
            .where(and_(AssetQuote.asset_id == asset.id, AssetQuote.data_status == "OK"))
            .order_by(AssetQuote.quote_timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    spot = Decimal(last_quote.last_price) if last_quote else None
    low, high, strikes = await get_strikes_in_range(db, asset, spot)

    warning = None
    if not strikes:
        has_series = (
            await db.execute(select(OptionSeries.id).where(OptionSeries.asset_id == asset.id, OptionSeries.active.is_(True)).limit(1))
        ).scalar_one_or_none()
        if not has_series:
            warning = "Nenhuma série ativa sincronizada para este ativo."
    return StrikeListResponse(
        asset=asset.symbol,
        spot_price=spot,
        range_low=low,
        range_high=high,
        strikes=strikes,
        data_avail=spot is not None,
        warning=warning,
    )
