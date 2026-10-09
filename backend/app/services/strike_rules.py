from datetime import date
from decimal import Decimal

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, OptionSeries, OptionType


async def get_strikes_in_range(db: AsyncSession, asset: Asset, spot_price: Decimal | None) -> tuple[Decimal | None, Decimal | None, list[Decimal]]:
    if spot_price is None:
        return None, None, []

    low = spot_price * (Decimal("1") - asset.lower_range_percent / Decimal("100"))
    high = spot_price * (Decimal("1") + asset.upper_range_percent / Decimal("100"))
    stmt: Select = (
        select(OptionSeries.strike)
        .where(
            and_(
                OptionSeries.asset_id == asset.id,
                OptionSeries.active.is_(True),
                OptionSeries.strike >= low,
                OptionSeries.strike <= high,
            )
        )
        .distinct()
        .order_by(OptionSeries.strike.asc())
    )
    values = (await db.execute(stmt)).scalars().all()
    return low, high, [Decimal(v) for v in values]


async def resolve_series_by_strike(
    db: AsyncSession,
    *,
    asset_id: int,
    option_type: OptionType,
    requested_strike: Decimal,
    expiration_date: date,
    tolerance: Decimal,
) -> tuple[OptionSeries | None, Decimal | None]:
    rows = (
        await db.execute(
            select(OptionSeries).where(
                OptionSeries.asset_id == asset_id,
                OptionSeries.option_type == option_type,
                OptionSeries.expiration_date == expiration_date,
                OptionSeries.active.is_(True),
            )
        )
    ).scalars().all()

    if not rows:
        return None, None

    best = min(rows, key=lambda s: abs(Decimal(s.strike) - requested_strike))
    diff = abs(Decimal(best.strike) - requested_strike)
    if diff <= tolerance:
        return best, (diff if diff != 0 else None)
    return None, None
