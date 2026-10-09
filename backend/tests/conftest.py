import os
from datetime import date, datetime, timezone
UTC = timezone.utc
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models import Asset, OptionSeries, OptionType, SystemSetting, User, UserRole
from app.models.base import Base

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/thlpro_test")


@pytest.fixture()
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP SEQUENCE IF EXISTS market_quote_sequence"))
        await conn.execute(text("CREATE SEQUENCE market_quote_sequence START 1"))
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.fixture()
async def seeded_db(db_session: AsyncSession):
    admin = User(name="Admin", email="admin@thlpro.local", password_hash=hash_password("TroqueEssaSenha123!"), role=UserRole.admin, active=True)
    user = User(name="Usuario", email="user@thlpro.local", password_hash=hash_password("SenhaSegura123!"), role=UserRole.user, active=True)
    db_session.add_all([admin, user])
    await db_session.flush()

    bova = Asset(
        symbol="BOVA11",
        name="BOVA11",
        asset_type="ETF",
        market="BOVESPA",
        enabled=True,
        tick_min=Decimal("0.01"),
        strike_interval=Decimal("1.0"),
        lower_range_percent=Decimal("10"),
        upper_range_percent=Decimal("10"),
        rtd_identifier_pattern="{SYMBOL}{CODE}_B_0",
        source="SEED",
    )
    abev = Asset(
        symbol="ABEV3",
        name="AMBEV S.A.",
        asset_type="ACAO",
        market="BOVESPA",
        enabled=True,
        tick_min=Decimal("0.01"),
        strike_interval=Decimal("0.50"),
        lower_range_percent=Decimal("10"),
        upper_range_percent=Decimal("10"),
        rtd_identifier_pattern="{SYMBOL}{CODE}_B_0",
        source="SEED",
    )
    db_session.add_all([bova, abev])
    await db_session.flush()

    db_session.add_all(
        [
            OptionSeries(asset_id=bova.id, option_symbol="BOVAJ171", option_type=OptionType.CALL, strike=Decimal("171"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAJ185", option_type=OptionType.CALL, strike=Decimal("185"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAJ200", option_type=OptionType.CALL, strike=Decimal("200"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAJ209", option_type=OptionType.CALL, strike=Decimal("209"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAV18451", option_type=OptionType.PUT, strike=Decimal("184.51"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAV18449", option_type=OptionType.PUT, strike=Decimal("184.49"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
            OptionSeries(asset_id=bova.id, option_symbol="BOVAV200", option_type=OptionType.PUT, strike=Decimal("200"), expiration_date=date(2026, 10, 16), expiration_month="OCT", active=True, source="B3"),
        ]
    )

    db_session.add_all(
        [
            SystemSetting(key="strike_tolerance", value={"value": 0.50}, description="Tolerância", updated_at=datetime.now(UTC)),
            SystemSetting(key="data_max_age_seconds", value={"value": 60}, description="Idade", updated_at=datetime.now(UTC)),
            SystemSetting(key="simulation_mode", value={"value": False}, description="Simulação", updated_at=datetime.now(UTC)),
            SystemSetting(key="default_expiration_count", value={"value": 6}, description="Padrão", updated_at=datetime.now(UTC)),
        ]
    )
    await db_session.commit()


@pytest.fixture()
async def client(db_session: AsyncSession, seeded_db):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture()
def sync_client(db_session: AsyncSession, seeded_db):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    try:
        yield tc
    finally:
        tc.close()
        app.dependency_overrides.clear()


async def _login(ac: AsyncClient, email: str, password: str) -> str:
    resp = await ac.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture()
async def admin_token(client):
    return await _login(client, "admin@thlpro.local", "TroqueEssaSenha123!")


@pytest.fixture()
async def user_token(client):
    return await _login(client, "user@thlpro.local", "SenhaSegura123!")
