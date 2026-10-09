import asyncio
from datetime import date, datetime, timezone
UTC = timezone.utc
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import Asset, OptionSeries, OptionType, SystemSetting, User, UserRole


async def seed() -> None:
    settings = get_settings()
    async with SessionLocal() as db:  # type: AsyncSession
        admin = (await db.execute(select(User).where(User.email == settings.admin_email))).scalar_one_or_none()
        if not admin:
            admin = User(
                name="Administrador",
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                role=UserRole.admin,
                active=True,
            )
            db.add(admin)

        defaults_assets = [
            {
                "symbol": "BOVA11",
                "name": "BOVA11",
                "asset_type": "ETF",
                "market": "BOVESPA",
                "enabled": True,
                "tick_min": Decimal("0.01"),
                "strike_interval": Decimal("1.0"),
                "lower_range_percent": Decimal("10"),
                "upper_range_percent": Decimal("10"),
                "rtd_identifier_pattern": "{SYMBOL}{CODE}_B_0",
                "source": "SEED",
            },
            {
                "symbol": "ABEV3",
                "name": "AMBEV S.A.",
                "asset_type": "ACAO",
                "market": "BOVESPA",
                "enabled": True,
                "tick_min": Decimal("0.01"),
                "strike_interval": Decimal("0.50"),
                "lower_range_percent": Decimal("10"),
                "upper_range_percent": Decimal("10"),
                "rtd_identifier_pattern": "{SYMBOL}{CODE}_B_0",
                "source": "SEED",
            },
        ]

        for item in defaults_assets:
            exists = (await db.execute(select(Asset).where(Asset.symbol == item["symbol"]))).scalar_one_or_none()
            if not exists:
                db.add(Asset(**item))

        defaults_settings = {
            "strike_tolerance": {"value": 0.50},
            "data_max_age_seconds": {"value": 60},
            "simulation_mode": {"value": False},
            "default_expiration_count": {"value": 6},
        }
        for key, value in defaults_settings.items():
            found = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
            if not found:
                db.add(
                    SystemSetting(
                        key=key,
                        value=value,
                        description=f"Configuração {key}",
                        updated_at=datetime.now(UTC),
                    )
                )

        await db.commit()

        # séries mínimas para desenvolvimento/testes (não fictícias para produção)
        bova = (await db.execute(select(Asset).where(Asset.symbol == "BOVA11"))).scalar_one()
        sample = (await db.execute(select(OptionSeries).where(OptionSeries.option_symbol == "BOVAJ200"))).scalar_one_or_none()
        if not sample:
            db.add(
                OptionSeries(
                    asset_id=bova.id,
                    option_symbol="BOVAJ200",
                    option_type=OptionType.CALL,
                    strike=Decimal("200"),
                    expiration_date=date(2026, 10, 16),
                    expiration_month="OCT",
                    active=True,
                    source="SEED",
                )
            )
            db.add(
                OptionSeries(
                    asset_id=bova.id,
                    option_symbol="BOVAV200",
                    option_type=OptionType.PUT,
                    strike=Decimal("200"),
                    expiration_date=date(2026, 10, 16),
                    expiration_month="OCT",
                    active=True,
                    source="SEED",
                )
            )
            await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
