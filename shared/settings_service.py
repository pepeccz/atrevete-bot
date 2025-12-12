"""
Dynamic Settings Service with TTL caching.

Provides access to system_settings stored in PostgreSQL with:
- 60-second TTL cache for performance
- Type validation (string, int, float, boolean, enum)
- Range validation (min/max for numeric types)
- Enum validation (allowed_values)
- Audit trail on updates

Usage:
    from shared.settings_service import get_settings_service

    service = await get_settings_service()

    # Get single setting
    hours = await service.get("confirmation_hours_before")  # Returns typed value

    # Get all settings grouped by category
    all_settings = await service.get_all()

    # Update setting
    await service.update("confirmation_hours_before", 72, changed_by="admin@example.com")
"""
import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import logging

from database.models import SystemSetting, SystemSettingsHistory, SettingValueType
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Cache TTL in seconds
CACHE_TTL_SECONDS = 60


class SettingsServiceError(Exception):
    """Base exception for SettingsService errors."""
    pass


class SettingNotFoundError(SettingsServiceError):
    """Raised when a setting key is not found."""
    pass


class SettingValidationError(SettingsServiceError):
    """Raised when a setting value fails validation."""
    pass


class SettingsService:
    """
    Singleton service for accessing and updating system settings.

    Uses a TTL-based cache to minimize database queries while ensuring
    settings are reasonably fresh.
    """

    _instance: "SettingsService | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, db_url: str | None = None):
        """Initialize the settings service."""
        self._db_url = db_url
        self._engine = None
        self._session_maker = None
        self._cache: dict[str, dict] = {}  # key -> {value, setting, expires_at}
        self._cache_lock = asyncio.Lock()
        self._initialized = False

    @classmethod
    async def get_instance(cls, db_url: str | None = None) -> "SettingsService":
        """Get or create the singleton instance."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_url)
                    await cls._instance._initialize()
        return cls._instance

    async def _initialize(self) -> None:
        """Initialize database connection."""
        if self._initialized:
            return

        if self._db_url is None:
            settings = get_settings()
            self._db_url = settings.DATABASE_URL

        # Ensure we use asyncpg driver
        if "postgresql://" in self._db_url and "+asyncpg" not in self._db_url:
            self._db_url = self._db_url.replace("postgresql://", "postgresql+asyncpg://")
        if "postgresql+psycopg://" in self._db_url:
            self._db_url = self._db_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")

        self._engine = create_async_engine(self._db_url, echo=False)
        self._session_maker = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._initialized = True
        logger.info("SettingsService initialized")

    async def _get_session(self) -> AsyncSession:
        """Get a database session."""
        if not self._initialized:
            await self._initialize()
        return self._session_maker()

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached value is still valid."""
        if key not in self._cache:
            return False
        return datetime.now(timezone.utc) < self._cache[key]["expires_at"]

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value by key.

        Uses TTL cache for performance. Returns the typed value
        (int, float, bool, or str depending on value_type).

        Args:
            key: The setting key
            default: Default value if setting not found (None by default)

        Returns:
            The typed setting value or default if not found
        """
        async with self._cache_lock:
            if self._is_cache_valid(key):
                return self._cache[key]["value"]

        # Cache miss or expired - fetch from database
        async with await self._get_session() as session:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == key)
            )
            setting = result.scalar_one_or_none()

            if setting is None:
                logger.warning(f"Setting not found: {key}")
                return default

            typed_value = self._convert_value(setting.value, setting.value_type)

            # Update cache
            async with self._cache_lock:
                self._cache[key] = {
                    "value": typed_value,
                    "setting": setting,
                    "expires_at": datetime.now(timezone.utc).timestamp() + CACHE_TTL_SECONDS,
                }
                self._cache[key]["expires_at"] = datetime.fromtimestamp(
                    self._cache[key]["expires_at"], tz=timezone.utc
                )

            return typed_value

    async def get_setting(self, key: str) -> SystemSetting | None:
        """
        Get the full SystemSetting object by key.

        Returns the complete setting including metadata (label, description, etc.).
        """
        async with await self._get_session() as session:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == key)
            )
            return result.scalar_one_or_none()

    async def get_all(self) -> dict[str, list[dict]]:
        """
        Get all settings grouped by category.

        Returns:
            Dict with category as key and list of setting dicts as value.
            Each setting dict includes: key, value, value_type, label, description,
            requires_restart, default_value, min_value, max_value, allowed_values
        """
        async with await self._get_session() as session:
            result = await session.execute(
                select(SystemSetting).order_by(SystemSetting.category, SystemSetting.display_order)
            )
            settings = result.scalars().all()

        grouped: dict[str, list[dict]] = {}
        for setting in settings:
            category = setting.category
            if category not in grouped:
                grouped[category] = []

            typed_value = self._convert_value(setting.value, setting.value_type)

            grouped[category].append({
                "id": str(setting.id),
                "key": setting.key,
                "value": typed_value,
                "value_type": setting.value_type,
                "default_value": self._convert_value(setting.default_value, setting.value_type),
                "min_value": setting.min_value,
                "max_value": setting.max_value,
                "allowed_values": setting.allowed_values,
                "label": setting.label,
                "description": setting.description,
                "requires_restart": setting.requires_restart,
                "display_order": setting.display_order,
                "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
                "updated_by": setting.updated_by,
            })

        return grouped

    async def update(
        self,
        key: str,
        value: Any,
        changed_by: str,
        change_reason: str | None = None
    ) -> SystemSetting:
        """
        Update a setting value with validation and audit trail.

        Args:
            key: The setting key
            value: The new value (will be validated)
            changed_by: Username/email of who made the change
            change_reason: Optional reason for the change

        Returns:
            The updated SystemSetting object

        Raises:
            SettingNotFoundError: If setting key doesn't exist
            SettingValidationError: If value fails validation
        """
        async with await self._get_session() as session:
            # Get current setting
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == key)
            )
            setting = result.scalar_one_or_none()

            if setting is None:
                raise SettingNotFoundError(f"Setting not found: {key}")

            # Validate the new value
            self._validate_value(value, setting)

            # Store previous value for audit
            previous_value = setting.value

            # Update the setting
            setting.value = value
            setting.updated_at = datetime.now(timezone.utc)
            setting.updated_by = changed_by

            # Create audit trail entry
            history_entry = SystemSettingsHistory(
                id=uuid4(),
                setting_id=setting.id,
                setting_key=key,
                previous_value=previous_value,
                new_value=value,
                changed_by=changed_by,
                change_reason=change_reason,
            )
            session.add(history_entry)

            await session.commit()
            await session.refresh(setting)

            # Invalidate cache
            async with self._cache_lock:
                if key in self._cache:
                    del self._cache[key]

            logger.info(f"Setting updated: {key} = {value} (by {changed_by})")
            return setting

    async def get_history(
        self,
        key: str | None = None,
        limit: int = 50,
        offset: int = 0
    ) -> list[dict]:
        """
        Get setting change history.

        Args:
            key: Optional filter by setting key
            limit: Maximum number of records (default 50)
            offset: Pagination offset

        Returns:
            List of history entries as dicts
        """
        async with await self._get_session() as session:
            query = select(SystemSettingsHistory).order_by(
                SystemSettingsHistory.changed_at.desc()
            )

            if key:
                query = query.where(SystemSettingsHistory.setting_key == key)

            query = query.limit(limit).offset(offset)
            result = await session.execute(query)
            entries = result.scalars().all()

            return [
                {
                    "id": str(entry.id),
                    "setting_key": entry.setting_key,
                    "previous_value": entry.previous_value,
                    "new_value": entry.new_value,
                    "changed_by": entry.changed_by,
                    "change_reason": entry.change_reason,
                    "changed_at": entry.changed_at.isoformat() if entry.changed_at else None,
                }
                for entry in entries
            ]

    def _convert_value(self, value: Any, value_type: str) -> Any:
        """Convert stored value to the correct Python type."""
        if value is None:
            return None

        if value_type == SettingValueType.INT.value:
            return int(value)
        elif value_type == SettingValueType.FLOAT.value:
            return float(value)
        elif value_type == SettingValueType.BOOLEAN.value:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        elif value_type == SettingValueType.STRING.value:
            return str(value)
        elif value_type == SettingValueType.ENUM.value:
            return str(value)
        return value

    def _validate_value(self, value: Any, setting: SystemSetting) -> None:
        """
        Validate a value against the setting's constraints.

        Raises:
            SettingValidationError: If validation fails
        """
        value_type = setting.value_type

        # Type validation
        if value_type == SettingValueType.INT.value:
            if not isinstance(value, int) or isinstance(value, bool):
                raise SettingValidationError(
                    f"Setting {setting.key} requires an integer value"
                )
        elif value_type == SettingValueType.FLOAT.value:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SettingValidationError(
                    f"Setting {setting.key} requires a numeric value"
                )
        elif value_type == SettingValueType.BOOLEAN.value:
            if not isinstance(value, bool):
                raise SettingValidationError(
                    f"Setting {setting.key} requires a boolean value"
                )
        elif value_type in (SettingValueType.STRING.value, SettingValueType.ENUM.value):
            if not isinstance(value, str):
                raise SettingValidationError(
                    f"Setting {setting.key} requires a string value"
                )

        # Range validation for numeric types
        if value_type in (SettingValueType.INT.value, SettingValueType.FLOAT.value):
            if setting.min_value is not None and value < setting.min_value:
                raise SettingValidationError(
                    f"Setting {setting.key} must be >= {setting.min_value}"
                )
            if setting.max_value is not None and value > setting.max_value:
                raise SettingValidationError(
                    f"Setting {setting.key} must be <= {setting.max_value}"
                )

        # Enum validation
        if value_type == SettingValueType.ENUM.value:
            if setting.allowed_values and value not in setting.allowed_values:
                raise SettingValidationError(
                    f"Setting {setting.key} must be one of: {setting.allowed_values}"
                )

    async def reset_to_default(self, key: str, changed_by: str) -> SystemSetting:
        """
        Reset a setting to its default value.

        Args:
            key: The setting key
            changed_by: Username/email of who made the change

        Returns:
            The updated SystemSetting object
        """
        setting = await self.get_setting(key)
        if setting is None:
            raise SettingNotFoundError(f"Setting not found: {key}")

        default_value = self._convert_value(setting.default_value, setting.value_type)
        return await self.update(
            key, default_value, changed_by, change_reason="Reset to default"
        )

    def clear_cache(self) -> None:
        """Clear the entire cache. Useful for testing."""
        self._cache.clear()
        logger.debug("Settings cache cleared")

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        cls._instance = None


# Convenience function for getting the service
async def get_settings_service(db_url: str | None = None) -> SettingsService:
    """
    Get the SettingsService singleton instance.

    Usage:
        service = await get_settings_service()
        value = await service.get("some_key")
    """
    return await SettingsService.get_instance(db_url)
