from fastapi import APIRouter, WebSocket, WebSocketDisconnect


from app.core.security import decode_token
from app.services.websocket_manager import manager


router = APIRouter(tags=["WebSocket"])



def _validate_ws_token(token: str) -> dict:
    try:
        return decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Token inválido para conexão WebSocket.") from exc



@router.websocket("/ws/market-data")
async def ws_market_data(websocket: WebSocket, token: str) -> None:
    try:
        _validate_ws_token(token)
    except ValueError:
        await websocket.close(code=4401)
        return


    await manager.connect_market(websocket)

    try:
        await manager.send_snapshot(websocket)
        await websocket.send_json(
            {
                "type": "status",
                "message": "Conectado ao canal de mercado.",
            }
        )

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
    finally:
        await manager.disconnect_market(websocket)



@router.websocket("/ws/client-status")
async def ws_client_status(websocket: WebSocket, token: str) -> None:
    try:
        payload = _validate_ws_token(token)

        if payload.get("role") != "admin":
            await websocket.close(code=4403)
            return
    except ValueError:
        await websocket.close(code=4401)
        return


    await manager.connect_status(websocket)

    try:
        await websocket.send_json(
            {
                "type": "status",
                "message": "Conectado ao canal de status de clientes.",
            }
        )

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
    finally:
        await manager.disconnect_status(websocket)