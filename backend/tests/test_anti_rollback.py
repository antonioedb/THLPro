from datetime import datetime, timedelta, timezone
UTC = timezone.utc

import pytest


@pytest.mark.asyncio
async def test_anti_rollback_rejeita_antigo(client, admin_token):
    now = datetime.now(UTC)
    new_quote = [{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 5.0, "bid": 4.9, "ask": 5.1, "quote_timestamp": now.isoformat(), "source": "RTD"}]
    old_quote = [{"asset": "BOVA11", "option_symbol": "BOVAJ200", "last_price": 4.0, "bid": 3.9, "ask": 4.1, "quote_timestamp": (now - timedelta(seconds=1)).isoformat(), "source": "RTD"}]

    ok = await client.post("/quotes", json=new_quote, headers={"Authorization": f"Bearer {admin_token}"})
    assert ok.status_code == 200 and ok.json()["accepted"] == 1

    rejected = await client.post("/quotes", json=old_quote, headers={"Authorization": f"Bearer {admin_token}"})
    assert rejected.status_code == 200
    assert rejected.json()["accepted"] == 0
    assert "anti-rollback" in rejected.json()["rejected"][0]["reason"].lower()
