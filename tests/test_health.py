"""Health endpoint tests — verifies /admin/health returns correct service status."""

from httpx import AsyncClient

from app.config.settings import settings


async def test_health_endpoint(async_client: AsyncClient) -> None:
    response = await async_client.get("/admin/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "timestamp" in data
    assert data["environment"] == settings.environment
