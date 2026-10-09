from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_client_from_api_key, get_current_user
from app.database import get_db
from app.models import Asset, Client, MarketQuote, OptionSeries, User
from app.schemas.quotes import QuoteBatchResponse, QuoteIn
from app.services.quote_validation import ensure_timestamp, round_by_tick, validate_future_skew
from app.services.websocket_manager import manager

router = APIRouter(prefix="/quotes", tags=["Cotações"])


async def _resolve_asset_series(db: AsyncSession, asset_symbol: str, option_symbol: str) -> tuple[Asset, OptionSeries]:
    asset = (await db.execute(select(Asset).where(Asset.symbol == asset_symbol.upper()))).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Ativo {asset_symbol} não cadastrado.")
    series = (
        await db.execute(
            select(OptionSeries).where(
                OptionSeries.option_symbol == option_symbol.upper(),
                OptionSeries.asset_id == asset.id,
                OptionSeries.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not series:
        raise HTTPException(status_code=404, detail=f"Série {option_symbol} não encontrada para o ativo informado.")
    return asset, series


@router.post("", response_model=QuoteBatchResponse, summary="Recebe lote de cotações de opções")
async def post_quotes(
    payload: list[QuoteIn],
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
) -> QuoteBatchResponse:
    return await _process_quotes(payload, db, user=current_user, client=None)


@router.post("/client", response_model=QuoteBatchResponse, summary="Recebe cotações via autenticação de cliente")
async def post_quotes_client(
    payload: list[QuoteIn],
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> QuoteBatchResponse:
    return await _process_quotes(payload, db, user=None, client=client)


async def _process_quotes(payload: list[QuoteIn], db: AsyncSession, user: User | None, client: Client | None) -> QuoteBatchResponse:
    settings = get_settings()
    accepted = 0
    rejected = []
    for idx, row in enumerate(payload):
        try:
            quote_ts = ensure_timestamp(row.quote_timestamp)
            validate_future_skew(quote_ts, settings.max_future_skew_seconds)
            asset, series = await _resolve_asset_series(db, row.asset, row.option_symbol)

            latest = (
                await db.execute(
                    select(MarketQuote)
                    .where(MarketQuote.option_series_id == series.id)
                    .order_by(desc(MarketQuote.quote_timestamp), desc(MarketQuote.received_at), desc(MarketQuote.sequence))
                    .limit(1)
                )
            ).scalar_one_or_none()

            if latest and quote_ts <= latest.quote_timestamp:
                # duplicado estrito se mesmo timestamp e mesmos preços
                if (
                    quote_ts == latest.quote_timestamp
                    and latest.last_price == row.last_price
                    and latest.bid == row.bid
                    and latest.ask == row.ask
                ):
                    rejected.append({"index": idx, "reason": "Cotação duplicada rejeitada (mesmo timestamp e preços)."})
                else:
                    rejected.append({"index": idx, "reason": "Cotação rejeitada por anti-rollback (timestamp antigo ou igual)."})
                continue

            rounded_last = round_by_tick(row.last_price, Decimal(asset.tick_min))
            rounded_bid = round_by_tick(row.bid, Decimal(asset.tick_min))
            rounded_ask = round_by_tick(row.ask, Decimal(asset.tick_min))
            premium = round_by_tick(row.premium if row.premium is not None else row.last_price, Decimal(asset.tick_min))

            item = MarketQuote(
                asset_id=asset.id,
                option_series_id=series.id,
                last_price=rounded_last,
                bid=rounded_bid,
                ask=rounded_ask,
                premium=premium,
                quote_timestamp=quote_ts,
                received_at=datetime.now(UTC),
                source=row.source,
                client_id=client.id if client else None,
                data_status=row.data_status,
            )
            db.add(item)
            await db.flush()
            await db.commit()
            accepted += 1

            await manager.broadcast_market(
                {
                    "type": "quote",
                    "data": {
                        "asset": asset.symbol,
                        "option_symbol": series.option_symbol,
                        "last_price": float(item.last_price) if item.last_price is not None else None,
                        "bid": float(item.bid) if item.bid is not None else None,
                        "ask": float(item.ask) if item.ask is not None else None,
                        "quote_timestamp": item.quote_timestamp.isoformat(),
                    },
                }
            )
        except HTTPException as exc:
            await db.rollback()
            rejected.append({"index": idx, "reason": exc.detail})
        except IntegrityError:
            await db.rollback()
            rejected.append({"index": idx, "reason": "Cotação duplicada rejeitada."})

    return QuoteBatchResponse(accepted=accepted, rejected=rejected)


@router.get("", summary="Consulta cotações por filtros")
async def get_quotes(
    asset: str | None = None,
    option_symbol: str | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(MarketQuote, OptionSeries, Asset).join(OptionSeries, MarketQuote.option_series_id == OptionSeries.id).join(Asset, MarketQuote.asset_id == Asset.id)
    if asset:
        stmt = stmt.where(Asset.symbol == asset.upper())
    if option_symbol:
        stmt = stmt.where(OptionSeries.option_symbol == option_symbol.upper())
    if from_ts:
        stmt = stmt.where(MarketQuote.quote_timestamp >= from_ts)
    if to_ts:
        stmt = stmt.where(MarketQuote.quote_timestamp <= to_ts)
    stmt = stmt.order_by(MarketQuote.quote_timestamp.desc()).limit(1000)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "asset": a.symbol,
            "option_symbol": s.option_symbol,
            "last_price": q.last_price,
            "bid": q.bid,
            "ask": q.ask,
            "premium": q.premium,
            "quote_timestamp": q.quote_timestamp,
            "received_at": q.received_at,
            "data_status": q.data_status,
            "sequence": q.sequence,
        }
        for q, s, a in rows
    ]


@router.get("/latest", summary="Retorna última cotação")
async def latest(
    asset: str,
    option_symbol: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    asset_obj, series = await _resolve_asset_series(db, asset, option_symbol)
    last = (
        await db.execute(
            select(MarketQuote)
            .where(MarketQuote.asset_id == asset_obj.id, MarketQuote.option_series_id == series.id)
            .order_by(MarketQuote.quote_timestamp.desc(), MarketQuote.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not last:
        return {"asset": asset_obj.symbol, "option_symbol": series.option_symbol, "data_status": "NA", "message": "N/D"}
    return {
        "asset": asset_obj.symbol,
        "option_symbol": series.option_symbol,
        "last_price": last.last_price,
        "bid": last.bid,
        "ask": last.ask,
        "premium": last.premium,
        "quote_timestamp": last.quote_timestamp,
        "received_at": last.received_at,
        "data_status": last.data_status,
    }


@router.get("/history", summary="Retorna histórico de cotações")
async def history(
    asset: str,
    option_symbol: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    asset_obj, series = await _resolve_asset_series(db, asset, option_symbol)
    rows = (
        await db.execute(
            select(MarketQuote)
            .where(MarketQuote.asset_id == asset_obj.id, MarketQuote.option_series_id == series.id)
            .order_by(MarketQuote.quote_timestamp.desc(), MarketQuote.sequence.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "last_price": x.last_price,
            "bid": x.bid,
            "ask": x.ask,
            "premium": x.premium,
            "quote_timestamp": x.quote_timestamp,
            "received_at": x.received_at,
            "data_status": x.data_status,
            "sequence": x.sequence,
        }
        for x in rows
    ]
