import pytest


@pytest.mark.asyncio
async def test_login_ok_and_me(client):
    resp = await client.post("/auth/login", json={"email": "admin@thlpro.local", "password": "TroqueEssaSenha123!"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@thlpro.local"


@pytest.mark.asyncio
async def test_login_credenciais_invalidas(client):
    resp = await client.post("/auth/login", json={"email": "admin@thlpro.local", "password": "errada"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_required(client):
    resp = await client.get("/users")
    assert resp.status_code == 401
