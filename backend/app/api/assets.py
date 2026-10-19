from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.deps import (
    get_current_user,
    get_user_or_client,
    require_admin,
)
from app.database import get_db
from app.models import (
    Asset,
    AssetQuote,
    Client,
    OptionSeries,
    OptionType,
    User,
)
from app.schemas.assets import (
    AssetCreate,
    AssetOut,
    AssetUpdate,
    StrikeCoverageOut,
    StrikeListResponse,
)
from app.schemas.auth import MessageResponse
from app.schemas.quotes import AssetQuoteIn
from app.services.capture_demand import capture_demand_store
from app.services.strike_rules import get_strikes_in_range
from app.services.websocket_manager import manager


UTC = timezone.utc


router = APIRouter(prefix="/assets", tags=["Ativos"])


async def _get_asset_by_ref(
    db: AsyncSession,
    ref: str,
) -> Asset:
    asset = None

    if ref.isdigit():
        asset = await db.get(Asset, int(ref))

    if not asset:
        asset = (
            await db.execute(
                select(Asset).where(Asset.symbol == ref.upper())
            )
        ).scalar_one_or_none()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Ativo não encontrado.",
        )

    return asset


def _get_third_friday(
    year: int,
    month: int,
) -> date:
    first_day = date(year, month, 1)
    weekday = first_day.weekday()

    days_until_friday = (4 - weekday) % 7
    first_friday = first_day.fromordinal(
        first_day.toordinal() + days_until_friday
    )

    return first_friday.fromordinal(
        first_friday.toordinal() + 14
    )


async def _get_monthly_expiration_dates(
    db: AsyncSession,
    asset_id: int,
    reference_date: date,
    month_count: int = 6,
) -> list[date]:
    monthly_dates: list[date] = []

    year = reference_date.year
    month = reference_date.month

    for _ in range(month_count):
        third_friday = _get_third_friday(year, month)

        if third_friday >= reference_date:
            monthly_dates.append(third_friday)

        month += 1

        if month > 12:
            month = 1
            year += 1

    if not monthly_dates:
        return []

    existing_dates = (
        await db.execute(
            select(OptionSeries.expiration_date)
            .where(
                OptionSeries.asset_id == asset_id,
                OptionSeries.active.is_(True),
                OptionSeries.expiration_date.in_(monthly_dates),
            )
            .group_by(OptionSeries.expiration_date)
            .order_by(OptionSeries.expiration_date.asc())
        )
    ).scalars().all()

    return list(existing_dates)


async def _broadcast_asset_capture(
    db: AsyncSession,
    asset: Asset,
) -> int:
    """
    Envia ao cliente RTD todas as séries ativas do ativo habilitado.

    Isso permite que o cliente comece a capturar as cotações das opções
    imediatamente após a habilitação, antes de o usuário escolher um
    strike específico no painel.
    """
    series_rows = (
        await db.execute(
            select(OptionSeries)
            .where(
                OptionSeries.asset_id == asset.id,
                OptionSeries.active.is_(True),
            )
            .order_by(
                OptionSeries.expiration_date,
                OptionSeries.option_type,
                OptionSeries.strike,
            )
        )
    ).scalars().all()

    assets_payload = [
        {
            "symbol": asset.symbol,
            "name": asset.name,
            "tick_min": str(asset.tick_min),
            "strike_interval": str(asset.strike_interval),
            "rtd_identifier_pattern": asset.rtd_identifier_pattern,
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
        for series in series_rows
    ]

    capture_payload = {
        "asset": asset.symbol,
        "strike": None,
        "assets": assets_payload,
        "active_series": series_payload,
    }

    capture_demand_store.set(capture_payload)

    await manager._broadcast(
        "capture_config",
        capture_payload,
    )

    return len(series_payload)


@router.get(
    "",
    response_model=list[AssetOut],
    summary="Lista ativos",
)
async def list_assets(
    enabled: bool | None = Query(default=None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AssetOut]:
    statement = select(Asset).order_by(Asset.symbol)

    if enabled is not None:
        statement = statement.where(Asset.enabled == enabled)

    rows = (await db.execute(statement)).scalars().all()

    return [AssetOut.model_validate(asset) for asset in rows]


@router.post(
    "",
    response_model=AssetOut,
    summary="Cria ativo (admin)",
)
async def create_asset(
    payload: AssetCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AssetOut:
    existing = (
        await db.execute(
            select(Asset).where(
                Asset.symbol == payload.symbol.upper()
            )
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ativo já cadastrado.",
        )

    item = Asset(**payload.model_dump())
    item.symbol = item.symbol.upper()

    db.add(item)
    await db.commit()
    await db.refresh(item)

    return AssetOut.model_validate(item)


@router.get(
    "/{ref}",
    response_model=AssetOut,
    summary="Busca ativo por ID ou símbolo",
)
async def get_asset(
    ref: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssetOut:
    asset = await _get_asset_by_ref(db, ref)

    return AssetOut.model_validate(asset)


@router.put(
    "/{ref}",
    response_model=AssetOut,
    summary="Atualiza ativo (admin)",
)
async def update_asset(
    ref: str,
    payload: AssetUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AssetOut:
    asset = await _get_asset_by_ref(db, ref)

    updates = payload.model_dump(exclude_none=True)

    new_symbol = updates.get("symbol")

    if new_symbol is not None:
        new_symbol = new_symbol.upper()

        if new_symbol != asset.symbol:
            existing = (
                await db.execute(
                    select(Asset).where(
                        Asset.symbol == new_symbol,
                        Asset.id != asset.id,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="Já existe outro ativo com este código.",
                )

        updates["symbol"] = new_symbol

    was_enabled = asset.enabled

    for key, value in updates.items():
        setattr(asset, key, value)

    await db.commit()
    await db.refresh(asset)

    # Gatilho: ao habilitar um ativo, solicita ao cliente RTD a captura
    # de todas as séries ativas daquele ativo.
    if not was_enabled and asset.enabled:
        await _broadcast_asset_capture(db, asset)

    return AssetOut.model_validate(asset)


@router.delete(
    "/{ref}",
    response_model=MessageResponse,
    summary="Desativa ativo (admin)",
)
async def delete_asset(
    ref: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    asset = await _get_asset_by_ref(db, ref)
    asset.enabled = False

    await db.commit()

    return MessageResponse(
        message="Ativo desativado com sucesso."
    )


@router.post(
    "/quotes",
    summary="Recebe cotações do ativo-base",
)
async def post_asset_quotes(
    payload: list[AssetQuoteIn],
    _: User | Client = Depends(get_user_or_client),
    db: AsyncSession = Depends(get_db),
) -> dict:
    accepted = 0
    rejected: list[dict] = []

    for index, row in enumerate(payload):
        symbol = row.asset.upper()

        asset = (
            await db.execute(
                select(Asset).where(Asset.symbol == symbol)
            )
        ).scalar_one_or_none()

        if not asset:
            rejected.append(
                {
                    "index": index,
                    "reason": "Ativo não cadastrado.",
                }
            )
            continue

        item = AssetQuote(
            asset_id=asset.id,
            last_price=Decimal(row.last_price),
            variation_points=(
                Decimal(row.variation_points)
                if row.variation_points is not None
                else None
            ),
            variation_pct=(
                Decimal(row.variation_pct)
                if row.variation_pct is not None
                else None
            ),
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

    return {
        "accepted": accepted,
        "rejected": rejected,
    }


@router.get(
    "/{symbol}/spot",
    summary="Retorna última cotação do ativo-base",
)
async def get_spot(
    symbol: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
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
        return {
            "asset": asset.symbol,
            "spot_price": None,
            "data_status": "NA",
            "message": "N/D",
        }

    return {
        "asset": asset.symbol,
        "spot_price": quote.last_price,
        "quote_timestamp": quote.quote_timestamp,
        "received_at": quote.received_at,
        "data_status": quote.data_status,
    }


@router.get(
    "/{symbol}/strikes",
    response_model=StrikeListResponse,
    summary="Lista strikes ativos dentro da faixa configurada",
)
@router.get(
    "/{symbol}/strikes/range",
    response_model=StrikeListResponse,
    summary="Lista strikes ativos dentro da faixa configurada",
)
async def get_strikes(
    symbol: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrikeListResponse:
    asset = await _get_asset_by_ref(db, symbol)

    last_quote = (
        await db.execute(
            select(AssetQuote)
            .where(
                and_(
                    AssetQuote.asset_id == asset.id,
                    AssetQuote.data_status == "OK",
                )
            )
            .order_by(AssetQuote.quote_timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    spot = Decimal(last_quote.last_price) if last_quote else None

    low, high, strikes_in_range = await get_strikes_in_range(
        db,
        asset,
        spot,
    )

    warning = None

    if not strikes_in_range:
        has_series = (
            await db.execute(
                select(OptionSeries.id)
                .where(
                    OptionSeries.asset_id == asset.id,
                    OptionSeries.active.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        if not has_series:
            warning = (
                "Nenhuma série ativa sincronizada para este ativo."
            )

    if spot is None or not strikes_in_range:
        return StrikeListResponse(
            asset=asset.symbol,
            spot_price=spot,
            range_low=low,
            range_high=high,
            strikes=strikes_in_range,
            strike_coverage=[],
            monthly_expirations=[],
            recommended_strike=None,
            data_avail=spot is not None,
            warning=warning,
        )

    today = datetime.now(UTC).date()

    monthly_expirations = await _get_monthly_expiration_dates(
        db=db,
        asset_id=asset.id,
        reference_date=today,
        month_count=6,
    )

    if not monthly_expirations:
        warning = (
            "Não foram encontrados vencimentos mensais ativos "
            "para este ativo."
        )

        return StrikeListResponse(
            asset=asset.symbol,
            spot_price=spot,
            range_low=low,
            range_high=high,
            strikes=strikes_in_range,
            strike_coverage=[],
            monthly_expirations=[],
            recommended_strike=None,
            data_avail=True,
            warning=warning,
        )

    rows = (
        await db.execute(
            select(
                OptionSeries.strike,
                OptionSeries.expiration_date,
                OptionSeries.option_type,
            )
            .where(
                OptionSeries.asset_id == asset.id,
                OptionSeries.active.is_(True),
                OptionSeries.expiration_date.in_(
                    monthly_expirations
                ),
                OptionSeries.strike >= low,
                OptionSeries.strike <= high,
            )
        )
    ).all()

    coverage_by_strike: dict[
        Decimal,
        dict[date, set[OptionType]],
    ] = defaultdict(lambda: defaultdict(set))

    for strike, expiration_date, option_type in rows:
        coverage_by_strike[Decimal(strike)][expiration_date].add(
            option_type
        )

    coverage: list[StrikeCoverageOut] = []

    for strike in strikes_in_range:
        normalized_strike = Decimal(strike)
        expiration_map = coverage_by_strike.get(
            normalized_strike,
            {},
        )

        call_expirations = sum(
            OptionType.CALL in expiration_map.get(
                expiration_date,
                set(),
            )
            for expiration_date in monthly_expirations
        )

        put_expirations = sum(
            OptionType.PUT in expiration_map.get(
                expiration_date,
                set(),
            )
            for expiration_date in monthly_expirations
        )

        complete_pairs = sum(
            (
                OptionType.CALL in expiration_map.get(
                    expiration_date,
                    set(),
                )
                and OptionType.PUT in expiration_map.get(
                    expiration_date,
                    set(),
                )
            )
            for expiration_date in monthly_expirations
        )

        dates_with_any_side = sorted(expiration_map.keys())

        coverage.append(
            StrikeCoverageOut(
                strike=normalized_strike,
                monthly_expirations=len(monthly_expirations),
                call_expirations=call_expirations,
                put_expirations=put_expirations,
                complete_pairs=complete_pairs,
                monthly_dates=dates_with_any_side,
            )
        )

    coverage.sort(
        key=lambda item: (
            item.complete_pairs != item.monthly_expirations,
            -item.complete_pairs,
            abs(item.strike - spot),
            item.strike,
        )
    )

    sorted_strikes = [item.strike for item in coverage]

    recommended_strike = next(
        (
            item.strike
            for item in coverage
            if item.has_full_pair_coverage
        ),
        None,
    )

    if recommended_strike is None and coverage:
        recommended_strike = coverage[0].strike

        warning = (
            "Nenhum strike possui CALL e PUT em todos os vencimentos "
            "mensais; foi recomendado o strike com maior cobertura."
        )

    return StrikeListResponse(
        asset=asset.symbol,
        spot_price=spot,
        range_low=low,
        range_high=high,
        strikes=sorted_strikes,
        strike_coverage=coverage,
        monthly_expirations=monthly_expirations,
        recommended_strike=recommended_strike,
        data_avail=True,
        warning=warning,
    )