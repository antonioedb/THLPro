from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "THLPro Backend"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/thlpro"
    test_database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/thlpro_test"
    secret_key: str = "troque-esta-chave-em-producao"
    access_token_expire_hours: int = 8
    admin_email: str = "admin@thlpro.local"
    admin_password: str = "TroqueEssaSenha123!"
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    log_level: str = "INFO"
    log_dir: str = "./logs"
    default_timezone: str = "America/Sao_Paulo"
    max_future_skew_seconds: int = 300
    use_redis: bool = False
    redis_url: str = "redis://localhost:6379/0"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
