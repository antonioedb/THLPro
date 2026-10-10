from datetime import datetime, timedelta, timezone


UTC = timezone.utc


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.deps import (
    get_client_from_api_key,
    get_current_user,
    require_admin,
    hash_api_key,
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
from app.api.quotes import _process_quotes


router = APIRouter(prefix="/clients", tags=["Clientes"])


LEASE_TTL_SECONDS = 600


class LeaseBatchRequest(BaseModel):
    option_series_ids: list[int]



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
        "message": "Lease adquirido com sucesso.",
    }



@router.post(
    "/lease/acquire-batch",
    summary="Cliente pede leases temporários para várias opções",
)
async def acquire_lease_batch(
    payload: LeaseBatchRequest,
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=LEASE_TTL_SECONDS)


    option_series_ids = list(dict.fromkeys(payload.option_series_ids))


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


    # No modo simulado, o cliente não adquire leases RTD.
    # Portanto, a exigência de lease é ignorada apenas para testes.
    simulation_payload = any(
        (row.source or "").upper() == "SIMULATED"
        for row in payload
    )


    if not simulation_payload:
        # Valida lease ativo para cada cotação enviada.
        # Prioriza option_series_id; mantém compatibilidade com option_symbol.
        for row in payload:
            if row.option_series_id is not None:
                series = (
                    await db.execute(
                        select(OptionSeries).where(
                            OptionSeries.id == row.option_series_id
                        )
                    )
                ).scalar_one_or_none()


                if not series:
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Opção {row.option_symbol} "
                            f"(id {row.option_series_id}) não encontrada."
                        ),
                    )
            else:
                series = (
                    await db.execute(
                        select(OptionSeries).where(
                            OptionSeries.option_symbol == row.option_symbol.upper()
                        )
                    )
                ).scalar_one_or_none()


                if not series:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Opção {row.option_symbol} não encontrada.",
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
                        f"Sem lease ativo para a opção {series.option_symbol}."
                    ),
                )


    # Processa as cotações.
    return await _process_quotes(
        payload,
        db,
        user=None,
        client=client,
    )



@router.get(
    "/config",
    response_model=ClientConfigResponse,
    summary="Retorna configuração para cliente autenticado",
)
async def client_config(
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> ClientConfigResponse:
    assets = (
        await db.execute(
            select(Asset)
            .where(Asset.enabled.is_(True))
            .order_by(Asset.symbol)
        )
    ).scalars().all()


    active_series = (
        await db.execute(
            select(OptionSeries)
            .where(OptionSeries.active.is_(True))
            .order_by(OptionSeries.option_symbol)
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


    asset_map = {asset.id: asset for asset in assets}


    series_payload = []


    for series in active_series:
        asset = asset_map.get(series.asset_id)


        if not asset:
            continue


        # O identificador RTD do Profit é o próprio ticker da opção.
        # Exemplos validados:
        # ABEVB267_B_0
        # BOVAJ200
        rtd_symbol = series.option_symbol


        series_payload.append(
            {
                "id": series.id,
                "option_symbol": series.option_symbol,
                "asset_id": series.asset_id,
                "option_type": series.option_type.value,
                "strike": str(series.strike),
                "expiration_date": series.expiration_date.isoformat(),
                "rtd_symbol": rtd_symbol,
            }
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
            status_code=404,
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