"""AUTH-01: Login endpoint integration tests."""

import uuid


async def test_login_valid_credentials(async_client, admin_user):
    """AUTH-01: Valid email+password returns JWT token pair."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "adminpass"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_invalid_password(async_client, admin_user):
    """AUTH-01: Wrong password returns 401."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "wrongpass"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(async_client):
    """AUTH-01: Unknown email returns 401."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.com", "password": "pass"},
    )
    assert response.status_code == 401


async def test_login_inactive_user(async_client, test_session):
    """AUTH-01: Inactive user cannot login."""
    from app.auth.models import User
    from app.auth.service import hash_password

    user = User(
        id=uuid.uuid4(),
        email="inactive@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=False,
    )
    test_session.add(user)
    await test_session.flush()

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@test.com", "password": "pass"},
    )
    assert response.status_code == 401


async def test_login_returns_valid_jwt(async_client, admin_user):
    """AUTH-01: Returned token can be decoded and contains correct claims."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "adminpass"},
    )
    from app.auth.service import decode_token

    token = response.json()["access_token"]
    payload = decode_token(token)
    assert payload["sub"] == str(admin_user.id)
    assert payload["is_admin"] is True
    assert payload["type"] == "access"
