from __future__ import annotations


from datetime import datetime, timezone
from threading import Lock
from typing import Any



class CaptureDemandStore:
    """
    Guarda em memória a última solicitação de captura sob demanda.


    O frontend solicita a captura ao selecionar ativo + strike.
    Os clientes RTD consultam esta solicitação pelo endpoint
    GET /clients/capture-config.
    """


    def __init__(self) -> None:
        self._lock = Lock()
        self._payload: dict[str, Any] | None = None
        self._updated_at: datetime | None = None


    def set(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload
            self._updated_at = datetime.now(timezone.utc)


    def get(self) -> dict[str, Any] | None:
        with self._lock:
            return self._payload


    def clear(self) -> None:
        with self._lock:
            self._payload = None
            self._updated_at = None



capture_demand_store = CaptureDemandStore()
