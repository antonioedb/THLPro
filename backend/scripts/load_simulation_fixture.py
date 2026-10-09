import asyncio
from datetime import date, datetime, timezone
UTC = timezone.utc
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Asset, OptionSeries, OptionType, SystemSetting


async def run() -> None:
    async with SessionLocal() as db:
        sim = (await db.execute(select(SystemSetting).where(SystemSetting.key == "simulation_mode"))).scalar_one_or_none()
        if not sim or sim.value.get("value") is not True:
            raise RuntimeError("Modo simulação está desativado. Ative simulation_mode antes de usar este script.")

        asset = (await db.execute(select(Asset).where(Asset.symbol == "BOVA11"))).scalar_one_or_none()
        if not asset:
            raise RuntimeError("Ativo BOVA11 não cadastrado.")

        symbols = [
            ("BOVASIMC185", OptionType.CALL, Decimal("185.00")),
            ("BOVASIMP185", OptionType.PUT, Decimal("185.00")),
        ]
        created = 0
        for symbol, otype, strike in symbols:
            found = (await db.execute(select(OptionSeries).where(OptionSeries.option_symbol == symbol))).scalar_one_or_none()
            if found:
                continue
            db.add(
                OptionSeries(
                    asset_id=asset.id,
                    option_symbol=symbol,
                    option_type=otype,
                    strike=strike,
                    expiration_date=date(2026, 12, 18),
                    expiration_month="DEC",
                    active=True,
                    source="SIMULATED",
                    needs_review=False,
                )
            )
            created += 1

        await db.commit()
        print(f"Séries simuladas criadas: {created}")


if __name__ == "__main__":
    asyncio.run(run())
