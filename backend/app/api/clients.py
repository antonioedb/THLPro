from datetime import datetime, timezone
UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_from_api_key, get_current_user, require_admin, hash_api_key
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


@router.post("/register", response_model=ClientRegisterResponse, summary="Registra cliente local e retorna API key (uma única vez)")
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
    await manager.broadcast_status({"type": "status", "data": {"client_id": client.id, "status": "connected"}})
    return ClientRegisterResponse(client_id=client.id, api_key=raw_key, message="Guarde esta chave com segurança; ela não será exibida novamente.")


@router.post("/heartbeat", response_model=ClientHeartbeatResponse, summary="Recebe heartbeat de cliente autenticado")
async def heartbeat(client: Client = Depends(get_client_from_api_key), db: AsyncSession = Depends(get_db)) -> ClientHeartbeatResponse:
    client.connected = True
    client.last_seen_at = datetime.now(UTC)
    await db.commit()
    return ClientHeartbeatResponse(message="Heartbeat recebido com sucesso.", server_time_utc=datetime.now(UTC))


@router.post("/quotes", response_model=QuoteBatchResponse, summary="Recebe cotações enviadas por cliente local")
async def client_quotes(
    payload: list[QuoteIn],
    client: Client = Depends(get_client_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> QuoteBatchResponse:
    return await _process_quotes(payload, db, user=None, client=client)


@router.get("/config", response_model=ClientConfigResponse, summary="Retorna configuração para cliente autenticado")
async def client_config(client: Client = Depends(get_client_from_api_key), db: AsyncSession = Depends(get_db)) -> ClientConfigResponse:
    assets = (await db.execute(select(Asset).where(Asset.enabled.is_(True)).order_by(Asset.symbol))).scalars().all()
    active_series = (await db.execute(select(OptionSeries).where(OptionSeries.active.is_(True)).order_by(OptionSeries.option_symbol))).scalars().all()

    assets_payload = [
        {
            "symbol": a.symbol,
            "name": a.name,
            "tick_min": str(a.tick_min),
            "strike_interval": str(a.strike_interval),
            "rtd_identifier_pattern": a.rtd_identifier_pattern,
        }
        for a in assets
    ]
    asset_map = {a.id: a for a in assets}
    series_payload = []
    for s in active_series:
        asset = asset_map.get(s.asset_id)
        if not asset:
            continue
        code = s.option_symbol.replace(asset.symbol, "")
        rtd_symbol = asset.rtd_identifier_pattern.replace("{SYMBOL}", asset.symbol).replace("{CODE}", code)
        series_payload.append(
            {
                "option_symbol": s.option_symbol,
                "asset_id": s.asset_id,
                "option_type": s.option_type.value,
                "strike": str(s.strike),
                "expiration_date": s.expiration_date.isoformat(),
                "rtd_symbol": rtd_symbol,
            }
        )
    return ClientConfigResponse(assets=assets_payload, active_series=series_payload)


@router.get("/status", response_model=list[ClientStatusItem], summary="Diagnóstico de clientes conectados (admin)")
async def status_clients(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[ClientStatusItem]:
    rows = (await db.execute(select(Client).order_by(Client.id))).scalars().all()
    return [ClientStatusItem.model_validate(r) for r in rows]


@router.post("/{client_id}/disconnect", summary="Força desconexão lógica de cliente (admin)")
async def disconnect_client(client_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    client.connected = False
    await db.commit()
    await manager.broadcast_status({"type": "status", "data": {"client_id": client.id, "status": "disconnected"}})
    return {"message": "Cliente desconectado com sucesso."}


@router.post("/{client_id}/reconnect", summary="Marca reconexão lógica de cliente (admin)")
async def reconnect_client(client_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    client.connected = True
    client.last_seen_at = datetime.now(UTC)
    await db.commit()
    await manager.broadcast_status({"type": "status", "data": {"client_id": client.id, "status": "connected"}})
    return {"message": "Cliente reconectado com sucesso."}
