from datetime import datetime, timedelta, timezone
UTC = timezone.utc

import pytest


@pytest.mark.asyncio
async def test_quotes_anti_rollback_and_duplicate(client, admin_token):
    ts = datetime.now(UTC)
    payload = [{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 1.234, "bid": 1.11, "ask": 1.25, "quote_timestamp": ts.isoformat(), "source": "RTD"}]

    first = await client.post("/quotes", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert first.status_code == 200
    assert first.json()["accepted"] == 1

    dup = await client.post("/quotes", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert dup.status_code == 200
    assert dup.json()["accepted"] == 0
    assert "duplicada" in dup.json()["rejected"][0]["reason"].lower() or "anti-rollback" in dup.json()["rejected"][0]["reason"].lower()

    old = [{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 1.50, "bid": 1.4, "ask": 1.6, "quote_timestamp": (ts - timedelta(seconds=5)).isoformat(), "source": "RTD"}]
    old_resp = await client.post("/quotes", json=old, headers={"Authorization": f"Bearer {admin_token}"})
    assert old_resp.json()["accepted"] == 0


@pytest.mark.asyncio
async def test_rounding_tick_and_missing_timestamp(client, admin_token):
    ts = datetime.now(UTC).isoformat()
    payload = [{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 1.234, "bid": 1.114, "ask": 1.236, "quote_timestamp": ts, "source": "RTD"}]
    send = await client.post("/quotes", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert send.status_code == 200

    latest = await client.get("/quotes/latest", params={"asset": "BOVA11", "option_symbol": "BOVAJ200"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert latest.status_code == 200
    assert latest.json()["last_price"] == "1.230000"

    bad = await client.post(
        "/quotes",
        json=[{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 1.2, "source": "RTD"}],
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad.status_code == 422
