import pytest


@pytest.mark.asyncio
async def test_client_lifecycle_register_heartbeat_status_disconnect(client, user_token, admin_token):
    reg = await client.post(
        "/clients/register",
        json={"client_name": "Desk-1", "computer_name": "PC-TRADER", "version": "1.0.0"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert reg.status_code == 200
    api_key = reg.json()["api_key"]
    client_id = reg.json()["client_id"]

    hb = await client.post("/clients/heartbeat", headers={"X-API-Key": api_key})
    assert hb.status_code == 200

    cfg = await client.get("/clients/config", headers={"X-API-Key": api_key})
    assert cfg.status_code == 200
    assert len(cfg.json()["assets"]) >= 1

    status = await client.get("/clients/status", headers={"Authorization": f"Bearer {admin_token}"})
    assert status.status_code == 200
    assert any(x["id"] == client_id for x in status.json())

    d = await client.post(f"/clients/{client_id}/disconnect", headers={"Authorization": f"Bearer {admin_token}"})
    assert d.status_code == 200
