from datetime import datetime, timezone
from decimal import Decimal






UTC = timezone.utc






from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.dialects.postgresql import insert
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







async def _resolve_asset_series(
    db: AsyncSession,
    asset_symbol: str,
    option_symbol: str,
) -> tuple[Asset, OptionSeries]:
    asset = (
        await db.execute(
            select(Asset).where(Asset.symbol == asset_symbol.upper())
        )
    ).scalar_one_or_none()






    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Ativo {asset_symbol} não cadastrado.",
        )






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
        raise HTTPException(
            status_code=404,
            detail=f"Série {option_symbol} não encontrada para o ativo informado.",
        )






    return asset, series







async def _resolve_series_by_id(
    db: AsyncSession,
    option_series_id: int,
) -> tuple[Asset, OptionSeries]:
    series = (
        await db.execute(
            select(OptionSeries).where(
                OptionSeries.id == option_series_id,
                OptionSeries.active.is_(True),
            )
        )
    ).scalar_one_or_none()






    if not series:
        raise HTTPException(
            status_code=404,
            detail=f"Série {option_series_id} não encontrada ou inativa.",
        )






    asset = (
        await db.execute(
            select(Asset).where(Asset.id == series.asset_id)
        )
    ).scalar_one_or_none()






    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Ativo da série {series.option_symbol} não encontrado.",
        )






    return asset, series







@router.post(
    "",
    response_model=QuoteBatchResponse,
    summary="Recebe lote de cotações de opções",
)
async def post_quotes(
    payload: list[QuoteIn],
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
) -> QuoteBatchResponse:
    return await _process_quotes(
        payload,
        db,
        user=current_user,
        client=None,
    )







@router.post(
    "/client",
    response_model=QuoteBatchResponse,
    summary="Recebe cotações via autenticação de cliente",
)
async def post_quotes_client(
    payload: list[QuoteIn],
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> QuoteBatchResponse:
    return await _process_quotes(
        payload,
        db,
        user=None,
        client=client,
    )







async def _process_quotes(
    payload: list[QuoteIn],
    db: AsyncSession,
    user: User | None,
    client: Client | None,
) -> QuoteBatchResponse:
    settings = get_settings()
    accepted = 0
    rejected: list[dict] = []






    # Captura o ID antes de qualquer commit.
    # Após commit(), atributos ORM podem expirar e causar MissingGreenlet.
    client_id = client.id if client else None






    # Deduplica o lote pela option_series_id.
    # O PostgreSQL não resolve conflito entre duas linhas novas
    # com a mesma chave dentro do mesmo INSERT.
    deduplicated: dict[int, QuoteIn] = {}





    for row in payload:
        if row.option_series_id is not None:
            deduplicated[row.option_series_id] = row






    rows_to_process = list(deduplicated.values())






    for idx, row in enumerate(rows_to_process):
        try:
            quote_ts = ensure_timestamp(row.quote_timestamp)
            validate_future_skew(
                quote_ts,
                settings.max_future_skew_seconds,
            )






            # Prioriza option_series_id enviado pelo cliente.
            # Mantém compatibilidade com payload antigo usando asset + option_symbol.
            if row.option_series_id is not None:
                asset, series = await _resolve_series_by_id(
                    db,
                    row.option_series_id,
                )
            else:
                asset, series = await _resolve_asset_series(
                    db,
                    row.asset,
                    row.option_symbol,
                )






            rounded_last = round_by_tick(
                row.last_price,
                Decimal(asset.tick_min),
            )






            rounded_bid = round_by_tick(
                row.bid,
                Decimal(asset.tick_min),
            )






            rounded_ask = round_by_tick(
                row.ask,
                Decimal(asset.tick_min),
            )






            premium = round_by_tick(
                row.premium if row.premium is not None else row.last_price,
                Decimal(asset.tick_min),
            )






            trade_count = row.trade_count
            quote_date = quote_ts.date()






            received_at = datetime.now(UTC)






            stmt = insert(MarketQuote).values(
                asset_id=asset.id,
                option_series_id=series.id,
                last_price=rounded_last,
                bid=rounded_bid,
                ask=rounded_ask,
                premium=premium,
                trade_count=trade_count,
                last_trade_count=trade_count,
                last_trade_date=None,
                quote_timestamp=quote_ts,
                received_at=received_at,
                source=row.source,
                client_id=client_id,
                data_status=row.data_status,
            )






            # Valor novo de NEG disponível no UPSERT.
            incoming_trade_count = stmt.excluded.trade_count



            # last_trade_count e last_trade_date avançam apenas
            # quando o NEG aumenta. Se for igual, menor ou nulo,
            # preservamos o último pregão com negócio confirmado.
            trade_increased = (
                incoming_trade_count.is_not(None)
                & (
                    MarketQuote.last_trade_count.is_(None)
                    | (
                        incoming_trade_count
                        > MarketQuote.last_trade_count
                    )
                )
            )






            stmt = stmt.on_conflict_do_update(
                constraint="uq_market_quotes_option_series",
                set_={
                    "last_price": rounded_last,
                    "bid": rounded_bid,
                    "ask": rounded_ask,
                    "premium": premium,
                    "trade_count": incoming_trade_count,
                    "last_trade_count": case(
                        (
                            trade_increased,
                            incoming_trade_count,
                        ),
                        else_=MarketQuote.last_trade_count,
                    ),
                    "last_trade_date": case(
                        (
                            trade_increased,
                            quote_date,
                        ),
                        else_=MarketQuote.last_trade_date,
                    ),
                    "quote_timestamp": quote_ts,
                    "received_at": received_at,
                    "source": row.source,
                    "client_id": client_id,
                    "data_status": row.data_status,
                },
                where=(
                    (MarketQuote.last_price.is_distinct_from(rounded_last))
                    | (MarketQuote.bid.is_distinct_from(rounded_bid))
                    | (MarketQuote.ask.is_distinct_from(rounded_ask))
                    | (
                        MarketQuote.trade_count.is_distinct_from(
                            incoming_trade_count
                        )
                    )
                ),
            )






            result = await db.execute(stmt)






            # rowcount == 0 significa que a cotação já existia
            # e nenhum valor relevante mudou.
            if result.rowcount == 0:
                rejected.append(
                    {
                        "index": idx,
                        "option_symbol": series.option_symbol,
                        "reason": "Valor igual, não atualiza.",
                    }
                )
                continue






            accepted += 1






            await manager.broadcast_market(
                {
                    "type": "quote",
                    "data": {
                        "asset": asset.symbol,
                        "option_symbol": series.option_symbol,
                        "last_price": float(rounded_last) if rounded_last is not None else None,
                        "bid": float(rounded_bid) if rounded_bid is not None else None,
                        "ask": float(rounded_ask) if rounded_ask is not None else None,
                        "trade_count": trade_count,
                        "quote_timestamp": quote_ts.isoformat(),
                    },
                }
            )






        except HTTPException as exc:
            await db.rollback()
            rejected.append(
                {
                    "index": idx,
                    "option_symbol": row.option_symbol,
                    "reason": exc.detail,
                }
            )






        except IntegrityError:
            await db.rollback()
            rejected.append(
                {
                    "index": idx,
                    "option_symbol": row.option_symbol,
                    "reason": "Cotação duplicada rejeitada.",
                }
            )






    await db.commit()






    return QuoteBatchResponse(accepted=accepted, rejected=rejected)







@router.get(
    "",
    summary="Consulta cotações por filtros",
)
async def get_quotes(
    asset: str | None = None,
    option_symbol: str | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(MarketQuote, OptionSeries, Asset)
        .join(
            OptionSeries,
            MarketQuote.option_series_id == OptionSeries.id,
        )
        .join(
            Asset,
            MarketQuote.asset_id == Asset.id,
        )
    )






    if asset:
        stmt = stmt.where(Asset.symbol == asset.upper())






    if option_symbol:
        stmt = stmt.where(
            OptionSeries.option_symbol == option_symbol.upper()
        )






    if from_ts:
        stmt = stmt.where(MarketQuote.quote_timestamp >= from_ts)






    if to_ts:
        stmt = stmt.where(MarketQuote.quote_timestamp <= to_ts)






    stmt = stmt.order_by(MarketQuote.quote_timestamp.desc()).limit(1000)






    rows = (await db.execute(stmt)).all()






    return [
        {
            "asset": asset_row.symbol,
            "option_symbol": series_row.option_symbol,
            "last_price": quote_row.last_price,
            "bid": quote_row.bid,
            "ask": quote_row.ask,
            "premium": quote_row.premium,
            "trade_count": quote_row.trade_count,
            "last_trade_count": quote_row.last_trade_count,
            "last_trade_date": quote_row.last_trade_date,
            "quote_timestamp": quote_row.quote_timestamp,
            "received_at": quote_row.received_at,
            "data_status": quote_row.data_status,
            "sequence": quote_row.sequence,
        }
        for quote_row, series_row, asset_row in rows
    ]







@router.get(
    "/latest",
    summary="Retorna última cotação",
)
async def latest(
    asset: str,
    option_symbol: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    asset_obj, series = await _resolve_asset_series(
        db,
        asset,
        option_symbol,
    )






    last = (
        await db.execute(
            select(MarketQuote)
            .where(
                MarketQuote.asset_id == asset_obj.id,
                MarketQuote.option_series_id == series.id,
            )
            .order_by(
                MarketQuote.quote_timestamp.desc(),
                MarketQuote.sequence.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()






    if not last:
        return {
            "asset": asset_obj.symbol,
            "option_symbol": series.option_symbol,
            "data_status": "NA",
            "message": "N/D",
        }






    return {
        "asset": asset_obj.symbol,
        "option_symbol": series.option_symbol,
        "last_price": last.last_price,
        "bid": last.bid,
        "ask": last.ask,
        "premium": last.premium,
        "trade_count": last.trade_count,
        "last_trade_count": last.last_trade_count,
        "last_trade_date": last.last_trade_date,
        "quote_timestamp": last.quote_timestamp,
        "received_at": last.received_at,
        "data_status": last.data_status,
    }







@router.get(
    "/history",
    summary="Retorna histórico de cotações",
)
async def history(
    asset: str,
    option_symbol: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    asset_obj, series = await _resolve_asset_series(
        db,
        asset,
        option_symbol,
    )






    rows = (
        await db.execute(
            select(MarketQuote)
            .where(
                MarketQuote.asset_id == asset_obj.id,
                MarketQuote.option_series_id == series.id,
            )
            .order_by(
                MarketQuote.quote_timestamp.desc(),
                MarketQuote.sequence.desc(),
            )
            .limit(limit)
        )
    ).scalars().all()






    return [
        {
            "last_price": quote.last_price,
            "bid": quote.bid,
            "ask": quote.ask,
            "premium": quote.premium,
            "trade_count": quote.trade_count,
            "last_trade_count": quote.last_trade_count,
            "last_trade_date": quote.last_trade_date,
            "quote_timestamp": quote.quote_timestamp,
            "received_at": quote.received_at,
            "data_status": quote.data_status,
            "sequence": quote.sequence,
        }
        for quote in rows
    ]