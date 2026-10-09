from datetime import datetime, timedelta, timezone
UTC = timezone.utc

import pytest


@pytest.mark.asyncio
async def test_simultaneous_posts_no_race(client, admin_token):
    t0 = datetime.now(UTC)

    r1 = await client.post(
        "/quotes",
        json=[
            {
                "asset": "BOVA11",
                "option_symbol": "BOVAJ200",
                "last_price": 4.0,
                "bid": 3.9,
                "ask": 4.1,
                "quote_timestamp": (t0 + timedelta(milliseconds=1)).isoformat(),
                "source": "RTD",
            }
        ],
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    r2 = await client.post(
        "/quotes",
        json=[
            {
                "asset": "BOVA11",
                "option_symbol": "BOVAJ200",
                "last_price": 5.0,
                "bid": 4.9,
                "ask": 5.1,
                "quote_timestamp": (t0 + timedelta(milliseconds=2)).isoformat(),
                "source": "RTD",
            }
        ],
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["accepted"] == 1
    assert r2.json()["accepted"] == 1
