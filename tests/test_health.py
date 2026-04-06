"""Tests for INFRA-01 (health), INFRA-02 (Swagger/OpenAPI), INFRA-03 (route prefix)."""


async def test_health_endpoint(async_client):
    """INFRA-01: Health endpoint responds with healthy status."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


async def test_swagger_ui_accessible(async_client):
    """INFRA-02: Swagger UI served at /docs."""
    response = await async_client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


async def test_openapi_schema_available(async_client):
    """INFRA-02: OpenAPI JSON schema available with correct title."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "LeadEnrich API"


async def test_api_routes_use_v1_prefix(async_client):
    """INFRA-03: All API routes (except health) use /api/v1/ prefix."""
    response = await async_client.get("/openapi.json")
    schema = response.json()
    paths = list(schema["paths"].keys())
    api_paths = [p for p in paths if p != "/health"]
    assert len(api_paths) > 0, "Expected at least one API route beyond /health"
    for path in api_paths:
        assert path.startswith("/api/v1/"), f"Route {path} does not use /api/v1/ prefix"
