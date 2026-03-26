"""Shared test fixtures — async DB session, HTTP client, and model imports."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("CLEVERTAP_ACCOUNT_ID", "test-account")
os.environ.setdefault("CLEVERTAP_PASSCODE", "test-passcode")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "testing")

from app.api.deps import get_db
from app.main import app
from app.models import (  # noqa: F401
    AppConfig,
    AttributionEvent,
    JourneyProgressSnapshot,
    Notification,
    NotificationEvent,
    UserJourneyState,
    UserProfile,
)
from app.models.base import Base

test_engine = create_async_engine(
    "sqlite+aiosqlite:///./test.db",
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def api_key_header() -> dict[str, str]:
    return {"X-API-Key": "test-secret-key"}
