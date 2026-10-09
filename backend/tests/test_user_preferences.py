import pytest


@pytest.mark.asyncio
async def test_user_preferences_default_update_and_validation(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}

    default_resp = await client.get("/users/me/preferences", headers=headers)
    assert default_resp.status_code == 200
    default_data = default_resp.json()
    assert default_data["selected_asset"] == "BOVA11"
    assert default_data["selected_strike"] is None
    assert default_data["expiration_count"] == 6
    assert default_data["show_calls"] is True
    assert default_data["show_puts"] is True
    assert default_data["auto_refresh"] is True
    assert default_data["refresh_interval"] == 3
    assert default_data["theme"] == "light"

    update_resp = await client.put(
        "/users/me/preferences",
        headers=headers,
        json={"theme": "dark", "expiration_count": 8},
    )
    assert update_resp.status_code == 200
    update_data = update_resp.json()
    assert update_data["theme"] == "dark"
    assert update_data["expiration_count"] == 8

    persisted_resp = await client.get("/users/me/preferences", headers=headers)
    assert persisted_resp.status_code == 200
    persisted_data = persisted_resp.json()
    assert persisted_data["theme"] == "dark"
    assert persisted_data["expiration_count"] == 8

    invalid_resp = await client.put(
        "/users/me/preferences",
        headers=headers,
        json={"expiration_count": 13},
    )
    assert invalid_resp.status_code == 422
