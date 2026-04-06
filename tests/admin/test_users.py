"""AUTH-03: User management admin endpoint integration tests."""


async def test_create_user(async_client, admin_token):
    """AUTH-03: Admin can create a new user."""
    response = await async_client.post(
        "/api/v1/admin/users",
        json={"email": "newuser@test.com", "password": "newpass123", "is_admin": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["is_admin"] is False
    assert data["is_active"] is True


async def test_create_user_non_admin_rejected(async_client, user_token):
    """AUTH-03: Non-admin cannot create users."""
    response = await async_client.post(
        "/api/v1/admin/users",
        json={"email": "bad@test.com", "password": "pass"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


async def test_list_users(async_client, admin_token, admin_user):
    """AUTH-03: Admin can list all users."""
    response = await async_client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    assert len(users) >= 1


async def test_delete_user_deactivates(async_client, admin_token, regular_user, mock_redis):
    """AUTH-03: Admin can deactivate a user via DELETE."""
    response = await async_client.delete(
        f"/api/v1/admin/users/{regular_user.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204
