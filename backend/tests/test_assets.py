from datetime import datetime, timezone
UTC = timezone.utc

import pytest
from sqlalchemy import insert

from app.models import Asset, AssetQuote


@pytest.mark.asyncio
async def test_assets_crud_and_permissions(client, admin_token, user_token):
    forbidden = await client.post(
        "/assets",
        json={
            "symbol": "PETR4",
            "name": "PETROBRAS",
            "asset_type": "ACAO",
            "market": "BOVESPA",
            "tick_min": "0.01",
            "strike_interval": "0.5",
            "lower_range_percent": "10",
            "upper_range_percent": "10",
            "rtd_identifier_pattern": "{SYMBOL}{CODE}_B_0",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code == 403

    created = await client.post(
        "/assets",
        json={
            "symbol": "PETR4",
            "name": "PETROBRAS",
            "asset_type": "ACAO",
            "market": "BOVESPA",
            "tick_min": "0.01",
            "strike_interval": "0.5",
            "lower_range_percent": "10",
            "upper_range_percent": "10",
            "rtd_identifier_pattern": "{SYMBOL}{CODE}_B_0",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200

    listed = await client.get("/assets", headers={"Authorization": f"Bearer {admin_token}"})
    assert listed.status_code == 200
    assert any(x["symbol"] == "PETR4" for x in listed.json())


@pytest.mark.asyncio
async def test_strikes_range_includes_all_and_sorted(client, admin_token):
    aq = await client.post(
        "/assets/quotes",
        json=[{"asset": "BOVA11", "last_price": 190, "quote_timestamp": datetime.now(UTC).isoformat(), "source": "RTD"}],
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert aq.status_code == 200

    resp = await client.get("/assets/BOVA11/strikes", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_avail"] is True
    assert body["strikes"] == sorted(body["strikes"])
    strikes = [float(x) for x in body["strikes"]]
    assert strikes[0] == 171.0
    assert strikes[-1] == 209.0
