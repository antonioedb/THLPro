from datetime import date
from decimal import Decimal

import pytest

from app.models import OptionType
from app.services.strike_rules import resolve_series_by_strike


@pytest.mark.asyncio
async def test_resolve_series_by_strike_tolerance(db_session, seeded_db):
    result, tol = await resolve_series_by_strike(
        db_session,
        asset_id=1,
        option_type=OptionType.PUT,
        requested_strike=Decimal("185.00"),
        expiration_date=date(2026, 10, 16),
        tolerance=Decimal("0.50"),
    )
    assert result is not None
    assert tol is not None
    assert tol <= Decimal("0.50")


@pytest.mark.asyncio
async def test_resolve_series_by_strike_outside_tolerance(db_session, seeded_db):
    result, tol = await resolve_series_by_strike(
        db_session,
        asset_id=1,
        option_type=OptionType.CALL,
        requested_strike=Decimal("183.00"),
        expiration_date=date(2026, 10, 16),
        tolerance=Decimal("0.50"),
    )
    assert result is None
    assert tol is None
