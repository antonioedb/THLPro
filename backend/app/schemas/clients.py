from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClientRegisterRequest(BaseModel):
    client_name: str = Field(min_length=2, max_length=120)
    computer_name: str = Field(min_length=2, max_length=120)
    version: str | None = Field(default=None, max_length=50)


class ClientRegisterResponse(BaseModel):
    client_id: int
    api_key: str
    message: str


class ClientHeartbeatResponse(BaseModel):
    message: str
    server_time_utc: datetime


class ClientStatusItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_name: str
    computer_name: str
    connected: bool
    last_seen_at: datetime | None
    last_error: str | None


class ClientConfigResponse(BaseModel):
    assets: list[dict]
    active_series: list[dict]
