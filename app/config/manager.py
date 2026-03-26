"""Runtime configuration manager — database-backed key-value store with in-memory cache."""

from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import AppConfig

logger = structlog.get_logger()

DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "defaults.yaml"


class ConfigManager:
    """Database-backed configuration with in-memory caching.

    Reads from the ``app_config`` table, caches values per instance,
    and supports seeding defaults from ``config/defaults.yaml``.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session
        self._cache: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        """Return config value for *key*, falling back to *default*."""
        if key in self._cache:
            return self._cache[key]

        result = await self.db.execute(
            select(AppConfig).where(AppConfig.key == key)
        )
        config = result.scalar_one_or_none()
        if config is None:
            return default

        self._cache[key] = config.value
        return config.value

    async def set(self, key: str, value: Any, updated_by: str = "system") -> None:
        """Upsert a config entry and refresh the in-memory cache."""
        result = await self.db.execute(
            select(AppConfig).where(AppConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config is not None:
            config.value = value
            config.updated_by = updated_by
        else:
            config = AppConfig(
                key=key,
                value=value,
                updated_by=updated_by,
                category="uncategorized",
            )
            self.db.add(config)

        await self.db.flush()
        self._cache[key] = value

    async def get_by_category(self, category: str) -> dict[str, Any]:
        """Return all config entries for a given category as a dict."""
        result = await self.db.execute(
            select(AppConfig).where(AppConfig.category == category)
        )
        configs = result.scalars().all()
        return {c.key: c.value for c in configs}

    async def seed_defaults(self) -> None:
        """Load defaults from YAML and insert any missing config entries."""
        raw = yaml.safe_load(DEFAULTS_PATH.read_text())
        count = 0
        for _category_group, entries in raw.items():
            for config_key, config_data in entries.items():
                result = await self.db.execute(
                    select(AppConfig).where(AppConfig.key == config_key)
                )
                if result.scalar_one_or_none() is not None:
                    continue

                item = AppConfig(
                    key=config_key,
                    value=config_data["value"],
                    description=config_data.get("description", ""),
                    category=config_data.get("category", "uncategorized"),
                    updated_by="system",
                )
                self.db.add(item)
                count += 1

        await self.db.flush()
        await self.db.commit()
        logger.info("Config defaults seeded", count=count)

    async def refresh_cache(self) -> None:
        """Reload all config entries into the in-memory cache."""
        result = await self.db.execute(select(AppConfig))
        configs = result.scalars().all()
        self._cache = {c.key: c.value for c in configs}
