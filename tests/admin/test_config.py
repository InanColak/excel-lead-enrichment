"""AUTH-02: Apollo API key configuration admin endpoint integration tests."""


async def test_set_apollo_key(async_client, admin_token):
    """AUTH-02: Admin can set Apollo API key."""
    response = await async_client.put(
        "/api/v1/admin/config/apollo-api-key",
        json={"api_key": "sk-test-apollo-key-12345"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key_set"] is True


async def test_get_apollo_key_masked(async_client, admin_token):
    """AUTH-02: Apollo API key returned masked (last 4 chars visible)."""
    # First set the key
    await async_client.put(
        "/api/v1/admin/config/apollo-api-key",
        json={"api_key": "sk-test-apollo-key-12345"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Then retrieve it
    response = await async_client.get(
        "/api/v1/admin/config/apollo-api-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key_set"] is True
    assert data["masked_key"] is not None
    # Should NOT contain the full key
    assert data["masked_key"] != "sk-test-apollo-key-12345"
    # Should end with last 4 chars of the original key
    assert data["masked_key"].endswith("2345")


async def test_get_apollo_key_when_not_set(async_client, admin_token):
    """AUTH-02: Returns key_set=False when no key configured."""
    response = await async_client.get(
        "/api/v1/admin/config/apollo-api-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key_set"] is False


async def test_set_apollo_key_non_admin_rejected(async_client, user_token):
    """AUTH-02: Non-admin cannot set API key."""
    response = await async_client.put(
        "/api/v1/admin/config/apollo-api-key",
        json={"api_key": "sk-secret"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403
