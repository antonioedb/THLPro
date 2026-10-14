from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.quotes import _process_quotes
from app.core.deps import (
    get_client_from_api_key,
    get_current_user,
    hash_api_key,
    require_admin,
)
from app.core.security import create_client_api_key
from app.database import get_db
from app.models import Asset, Client, OptionSeries, User
from app.schemas.clients import (
    ClientConfigResponse,
    ClientHeartbeatResponse,
    ClientRegisterRequest,
    ClientRegisterResponse,
    ClientStatusItem,
)
from app.schemas.quotes import QuoteBatchResponse, QuoteIn
from app.services.websocket_manager import manager


UTC = timezone.utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["Clientes"])

LEASE_TTL_SECONDS = 600

# Faixa de strikes enviada ao cliente RTD:
# 15% abaixo e 15% acima do último preço do ativo-base.
OPTION_STRIKE_RANGE_PCT = Decimal("0.15")

# Inclui o mês atual e os seis meses seguintes.
# Ex.: em outubro, traz opções até abril do ano seguinte.
OPTION_MONTHS_AHEAD = 6

# Regra compartilhada com GET /options/by-strike:
# para cada mês, a data com a maior quantidade de séries ativas é a
# data mensal escolhida para a interface e para a captura RTD.
MONTHLY_EXPIRATION_RULE = "MOST_ACTIVE_DATE_PER_MONTH"


class LeaseBatchRequest(BaseModel):
    option_series_ids: list[int]


def add_months(reference: date, months: int) -> date:
    """
    Soma meses a uma data e limita o dia ao último dia válido do mês.

    Exemplo:
    31/01 + 1 mês = 28/02 ou 29/02.
    """
    target_month = reference.month - 1 + months
    target_year = reference.year + target_month // 12
    target_month = target_month % 12 + 1

    first_day_next_month = (
        date(target_year + 1, 1, 1)
        if target_month == 12
        else date(target_year, target_month + 1, 1)
    )
    last_day_target_month = first_day_next_month - timedelta(days=1)

    return date(
        target_year,
        target_month,
        min(reference.day, last_day_target_month.day),
    )


def parse_spot_values(
    spot_values: list[str] | None,
) -> dict[str, Decimal]:
    """
    Converte parâmetros repetidos:

        ?spot=BOVA11:205.55&spot=ABEV3:15.99

    em:

        {"BOVA11": Decimal("205.55"), "ABEV3": Decimal("15.99")}
    """
    parsed: dict[str, Decimal] = {}

    for raw_value in spot_values or []:
        if ":" not in raw_value:
            continue

        raw_symbol, raw_price = raw_value.split(":", 1)
        symbol = raw_symbol.strip().upper()
        normalized_price = raw_price.strip().replace(",", ".")

        if not symbol:
            continue

        try:
            price = Decimal(normalized_price)
        except InvalidOperation:
            continue

        if price <= 0:
            continue

        parsed[symbol] = price

    return parsed


async def get_monthly_expiration_dates(
    db: AsyncSession,
    asset_id: int,
    start_date: date,
    end_date: date,
) -> list[date]:
    """
    Retorna uma data de vencimento por mês.

    A data mensal é aquela que possui a maior quantidade de séries ativas
    no cadastro para o ativo e mês correspondente. Em empate, mantém a
    data mais próxima, pois a consulta é ordenada por data crescente.

    Esta é a mesma regra usada pelo endpoint /options/by-strike.
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
                OptionSeries.expiration_date >= start_date,
                OptionSeries.expiration_date <= end_date,
            )
            .group_by(OptionSeries.expiration_date)
            .order_by(OptionSeries.expiration_date.asc())
        )
    ).all()

    monthly_by_month: dict[tuple[int, int], tuple[date, int]] = {}

    for expiration_date, series_count in rows:
        month_key = (
            expiration_date.year,
            expiration_date.month,
        )
        current = monthly_by_month.get(month_key)

        if current is None or series_count > current[1]:
            monthly_by_month[month_key] = (
                expiration_date,
                series_count,
            )

    return [
        expiration_date
        for expiration_date, _ in sorted(
            monthly_by_month.values(),
            key=lambda item: item[0],
        )
    ]


@router.post(
    "/register",
    response_model=ClientRegisterResponse,
    summary="Registra cliente local e retorna API key (uma única vez)",
)
async def register_client(
    payload: ClientRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClientRegisterResponse:
    raw_key = create_client_api_key()

    client = Client(
        user_id=current_user.id,
        client_name=payload.client_name,
        computer_name=payload.computer_name,
        api_key_hash=hash_api_key(raw_key),
        version=payload.version,
        connected=True,
        last_seen_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    db.add(client)
    await db.commit()
    await db.refresh(client)

    await manager.broadcast_status(
        {
            "type": "status",
            "data": {
                "client_id": client.id,
                "status": "connected",
            },
        }
    )

    return ClientRegisterResponse(
        client_id=client.id,
        api_key=raw_key,
        message="Guarde esta chave com segurança; ela não será exibida novamente.",
    )


@router.post(
    "/heartbeat",
    response_model=ClientHeartbeatResponse,
    summary="Recebe heartbeat de cliente autenticado",
)
async def heartbeat(
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> ClientHeartbeatResponse:
    client.connected = True
    client.last_seen_at = datetime.now(UTC)
    await db.commit()

    return ClientHeartbeatResponse(
        message="Heartbeat recebido com sucesso.",
        server_time_utc=datetime.now(UTC),
    )


@router.post(
    "/lease/acquire",
    summary="Cliente pede lease temporário para atualizar uma opção",
)
async def acquire_lease(
    option_series_id: int,
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=LEASE_TTL_SECONDS)

    result = await db.execute(
        text(
            """
            INSERT INTO leases (option_series_id, client_id, expires_at)
            VALUES (:oid, :cid, :exp)
            ON CONFLICT (option_series_id)
            DO UPDATE SET
                client_id = :cid,
                expires_at = :exp
            WHERE leases.expires_at < :now
               OR leases.client_id = :cid
            RETURNING client_id
            """
        ),
        {
            "oid": option_series_id,
            "cid": client.id,
            "exp": expires_at,
            "now": now,
        },
    )

    row = result.fetchone()

    if row is None:
        raise HTTPException(
            status_code=409,
            detail="Lease ativo de outro cliente",
        )

    await db.commit()

    return {
        "option_series_id": option_series_id,
        "expires_at": expires_at.isoformat(),
        "message": "Lease adquirido ou renovado com sucesso.",
    }


@router.post(
    "/lease/acquire-batch",
    summary="Cliente pede ou renova leases temporários para várias opções",
)
async def acquire_lease_batch(
    payload: LeaseBatchRequest,
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=LEASE_TTL_SECONDS)

    option_series_ids = list(
        dict.fromkeys(
            option_series_id
            for option_series_id in payload.option_series_ids
            if option_series_id > 0
        )
    )

    if not option_series_ids:
        return {
            "acquired": [],
            "rejected": [],
            "expires_at": expires_at.isoformat(),
        }

    result = await db.execute(
        text(
            """
            INSERT INTO leases (option_series_id, client_id, expires_at)
            SELECT oid, :cid, :exp
            FROM unnest(CAST(:oids AS int[])) AS oid
            ON CONFLICT (option_series_id)
            DO UPDATE SET
                client_id = :cid,
                expires_at = :exp
            WHERE leases.expires_at < :now
               OR leases.client_id = :cid
            RETURNING option_series_id
            """
        ),
        {
            "oids": option_series_ids,
            "cid": client.id,
            "exp": expires_at,
            "now": now,
        },
    )

    acquired_rows = result.fetchall()
    acquired = [row[0] for row in acquired_rows]

    await db.commit()

    rejected = [
        option_series_id
        for option_series_id in option_series_ids
        if option_series_id not in acquired
    ]

    return {
        "acquired": acquired,
        "rejected": rejected,
        "expires_at": expires_at.isoformat(),
    }


@router.post(
    "/lease/release",
    summary="Cliente libera o lease de uma opção",
)
async def release_lease(
    option_series_id: int,
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        text(
            """
            DELETE FROM leases
            WHERE option_series_id = :oid
              AND client_id = :cid
            """
        ),
        {
            "oid": option_series_id,
            "cid": client.id,
        },
    )

    await db.commit()

    return {
        "released": True,
        "message": "Lease liberado com sucesso.",
    }


@router.post(
    "/quotes",
    response_model=QuoteBatchResponse,
    summary="Recebe cotações enviadas por cliente local",
)
async def client_quotes(
    payload: list[QuoteIn],
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> QuoteBatchResponse:
    now = datetime.now(UTC)

    simulation_payload = any(
        (row.source or "").upper() == "SIMULATED"
        for row in payload
    )

    if not simulation_payload:
        for row in payload:
            if row.option_series_id is None and not row.option_symbol:
                continue

            if row.option_series_id is not None:
                series = (
                    await db.execute(
                        select(OptionSeries).where(
                            OptionSeries.id == row.option_series_id
                        )
                    )
                ).scalar_one_or_none()
            else:
                series = (
                    await db.execute(
                        select(OptionSeries).where(
                            OptionSeries.option_symbol
                            == row.option_symbol.upper()
                        )
                    )
                ).scalar_one_or_none()

            if not series:
                identifier = (
                    f"id {row.option_series_id}"
                    if row.option_series_id is not None
                    else row.option_symbol
                )

                raise HTTPException(
                    status_code=404,
                    detail=f"Opção {identifier} não encontrada.",
                )

            lease = (
                await db.execute(
                    text(
                        """
                        SELECT 1
                        FROM leases
                        WHERE option_series_id = :oid
                          AND client_id = :cid
                          AND expires_at > :now
                        """
                    ),
                    {
                        "oid": series.id,
                        "cid": client.id,
                        "now": now,
                    },
                )
            ).fetchone()

            if lease is None:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Sem lease ativo para a opção "
                        f"{series.option_symbol}."
                    ),
                )

    return await _process_quotes(
        payload,
        db,
        user=None,
        client=client,
    )


@router.get(
    "/config",
    response_model=ClientConfigResponse,
    summary="Retorna configuração filtrada para cliente autenticado",
)
async def client_config(
    include_series: bool = Query(
        default=True,
        description=(
            "Quando false, devolve apenas os ativos-base habilitados. "
            "Use na primeira chamada do cliente."
        ),
    ),
    spot: list[str] | None = Query(
        default=None,
        description=(
            "Spot por ativo, em parâmetros repetidos. "
            "Exemplo: spot=BOVA11:205.55&spot=ABEV3:15.99"
        ),
    ),
    _: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> ClientConfigResponse:
    """
    Entrega ativos habilitados e séries mensais adequadas à captura RTD.

    Critérios:
    - ativo habilitado;
    - série ativa;
    - uma data mensal por mês, definida pela maior quantidade de séries;
    - vencimentos entre hoje e os seis meses seguintes;
    - strike entre −15% e +15% do spot recebido pelo cliente.
    """
    request_started_at = time.perf_counter()

    assets = (
        await db.execute(
            select(Asset)
            .where(Asset.enabled.is_(True))
            .order_by(Asset.symbol)
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
        for asset in assets
    ]

    if not include_series:
        logger.info(
            "Config RTD: somente ativos-base retornados. ativos=%s",
            len(assets),
        )

        return ClientConfigResponse(
            assets=assets_payload,
            active_series=[],
        )

    if not assets:
        logger.warning("Config RTD: nenhum ativo habilitado encontrado.")

        return ClientConfigResponse(
            assets=assets_payload,
            active_series=[],
        )

    spot_by_symbol = parse_spot_values(spot)

    if not spot_by_symbol:
        logger.warning(
            "Config RTD: nenhuma cotação spot válida recebida. "
            "Parâmetros=%s",
            spot or [],
        )

        return ClientConfigResponse(
            assets=assets_payload,
            active_series=[],
        )

    today = datetime.now(UTC).date()
    max_expiration_date = add_months(today, OPTION_MONTHS_AHEAD)

    selected_series: list[OptionSeries] = []

    for asset in assets:
        asset_symbol = asset.symbol.upper()
        asset_spot = spot_by_symbol.get(asset_symbol)

        if asset_spot is None:
            logger.info(
                "Config RTD mensal: ativo=%s ignorado sem spot.",
                asset_symbol,
            )
            continue

        min_strike = asset_spot * (
            Decimal("1") - OPTION_STRIKE_RANGE_PCT
        )
        max_strike = asset_spot * (
            Decimal("1") + OPTION_STRIKE_RANGE_PCT
        )

        query_started_at = time.perf_counter()

        monthly_expirations = await get_monthly_expiration_dates(
            db=db,
            asset_id=asset.id,
            start_date=today,
            end_date=max_expiration_date,
        )

        if not monthly_expirations:
            logger.warning(
                "Config RTD mensal: ativo=%s id=%s não possui "
                "vencimentos ativos na janela %s..%s.",
                asset_symbol,
                asset.id,
                today.isoformat(),
                max_expiration_date.isoformat(),
            )
            continue

        rows = (
            await db.execute(
                select(OptionSeries)
                .where(
                    OptionSeries.asset_id == asset.id,
                    OptionSeries.active.is_(True),
                    OptionSeries.expiration_date.in_(monthly_expirations),
                    OptionSeries.strike >= min_strike,
                    OptionSeries.strike <= max_strike,
                )
                .order_by(
                    OptionSeries.expiration_date,
                    OptionSeries.option_type,
                    OptionSeries.strike,
                    OptionSeries.option_symbol,
                )
            )
        ).scalars().all()

        query_elapsed_ms = (
            time.perf_counter() - query_started_at
        ) * 1000

        expiration_text = ",".join(
            expiration.isoformat()
            for expiration in monthly_expirations
        )

        by_expiration = Counter(
            series.expiration_date
            for series in rows
        )

        counts_text = ",".join(
            f"{expiration.isoformat()}:{by_expiration.get(expiration, 0)}"
            for expiration in monthly_expirations
        )

        logger.info(
            "Config RTD mensal: ativo=%s id=%s spot=%s "
            "faixa_strike=%s..%s vencimentos=%s "
            "séries_por_vencimento=%s séries=%s consulta=%.1fms",
            asset_symbol,
            asset.id,
            asset_spot,
            min_strike,
            max_strike,
            expiration_text,
            counts_text,
            len(rows),
            query_elapsed_ms,
        )

        selected_series.extend(rows)

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

    elapsed_ms = (time.perf_counter() - request_started_at) * 1000

    logger.info(
        "Config RTD finalizada: regra_mensal=%s ativos=%s spots=%s "
        "séries=%s tempo_total=%.1fms",
        MONTHLY_EXPIRATION_RULE,
        len(assets),
        len(spot_by_symbol),
        len(series_payload),
        elapsed_ms,
    )

    return ClientConfigResponse(
        assets=assets_payload,
        active_series=series_payload,
    )


@router.get(
    "/status",
    response_model=list[ClientStatusItem],
    summary="Diagnóstico de clientes conectados (admin)",
)
async def status_clients(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ClientStatusItem]:
    rows = (
        await db.execute(select(Client).order_by(Client.id))
    ).scalars().all()

    return [
        ClientStatusItem.model_validate(row)
        for row in rows
    ]


@router.post(
    "/{client_id}/disconnect",
    summary="Força desconexão lógica de cliente (admin)",
)
async def disconnect_client(
    client_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await db.get(Client, client_id)

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Cliente não encontrado.",
        )

    client.connected = False
    await db.commit()

    await manager.broadcast_status(
        {
            "type": "status",
            "data": {
                "client_id": client.id,
                "status": "disconnected",
            },
        }
    )

    return {
        "message": "Cliente desconectado com sucesso.",
    }


@router.post(
    "/{client_id}/reconnect",
    summary="Marca reconexão lógica de cliente (admin)",
)
async def reconnect_client(
    client_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await db.get(Client, client_id)

    if not client:
        raise HTTPException(
            status_code=400,
            detail="Cliente não encontrado.",
        )

    client.connected = True
    client.last_seen_at = datetime.now(UTC)
    await db.commit()

    await manager.broadcast_status(
        {
            "type": "status",
            "data": {
                "client_id": client.id,
                "status": "connected",
            },
        }
    )

    return {
        "message": "Cliente reconectado com sucesso.",
    }