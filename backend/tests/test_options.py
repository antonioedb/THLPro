import pytest


@pytest.mark.asyncio
async def test_by_strike_tolerance_inside_and_outside(client, admin_token):
    ok = await client.get(
        "/options/by-strike",
        params={"asset": "BOVA11", "strike": "185", "expiration_count": 1, "types": "PUT"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ok.status_code == 200
    items = ok.json()["items"]
    assert float(items[0]["matched_strike"]) in [184.49, 184.51]

    fail = await client.get(
        "/options/by-strike",
        params={"asset": "BOVA11", "strike": "183.98", "expiration_count": 1, "types": "CALL"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fail.status_code == 200
    assert fail.json()["items"][0]["option_symbol"] is None


@pytest.mark.asyncio
async def test_sync_upload_fixture(client, admin_token):
    resp = await client.post(
        "/options/synchronize",
        json={"source": "upload", "asset_id": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert "created" in resp.json()
