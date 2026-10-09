import pytest

from app.services.websocket_manager import WebSocketManager


class DummyWS:
    def __init__(self):
        self.messages = []

    async def accept(self):
        return None

    async def send_json(self, payload):
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_websocket_manager_broadcast_and_snapshot():
    manager = WebSocketManager()
    ws = DummyWS()

    await manager.connect_market(ws)
    await manager.send_snapshot(ws)
    assert ws.messages[0]["type"] == "snapshot"

    event = {"type": "quote", "data": {"option_symbol": "BOVAJ200", "last_price": 2.1}}
    await manager.broadcast_market(event)

    assert any(m.get("type") == "quote" for m in ws.messages)
    assert manager._snapshot["BOVAJ200"]["last_price"] == 2.1
