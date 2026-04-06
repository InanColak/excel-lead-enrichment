"""AUTH-01: Token refresh endpoint integration tests."""


async def test_refresh_valid_token(async_client, admin_user):
    """Refresh with valid refresh_token returns new token pair."""
    login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "adminpass"},
    )
    refresh_token = login.json()["refresh_token"]

    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_refresh_with_access_token_rejected(async_client, admin_user):
    """Refresh endpoint rejects access tokens (wrong type)."""
    login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "adminpass"},
    )
    access_token = login.json()["access_token"]

    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert response.status_code == 401


async def test_refresh_with_invalid_token(async_client):
    """Refresh endpoint rejects garbage tokens."""
    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not-a-valid-token"},
    )
    assert response.status_code == 401
