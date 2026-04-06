"""D-07: Token revocation and blocklist integration tests."""

from unittest.mock import AsyncMock


async def test_logout_revokes_token(async_client, admin_user, admin_token, mock_redis):
    """AUTH-01: Logout adds token JTI to Redis blocklist via setex."""
    response = await async_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204
    # Verify that redis.setex was called with a blocklist: prefix key
    mock_redis.setex.assert_called()
    call_args = mock_redis.setex.call_args
    assert call_args[0][0].startswith("blocklist:")


async def test_revoked_token_rejected(async_client, admin_user, admin_token, mock_redis):
    """D-07: Request with revoked token returns 401."""
    # Simulate token being in blocklist (exists returns 1 = truthy)
    mock_redis.exists = AsyncMock(return_value=1)
    response = await async_client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 401


async def test_request_without_token_returns_401(async_client):
    """Protected endpoint returns 401 without auth header."""
    response = await async_client.get("/api/v1/admin/users")
    assert response.status_code in (401, 403)
