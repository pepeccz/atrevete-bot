"""
System Settings API Endpoints for Admin Panel

Provides REST endpoints for:
- GET /api/admin/settings - List all settings grouped by category
- GET /api/admin/settings/{key} - Get single setting
- PUT /api/admin/settings/{key} - Update setting value
- GET /api/admin/settings/history - Get change history
- POST /api/admin/settings/restart-worker - Restart confirmation worker
"""

import logging
from datetime import datetime

import httpx
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.routes.admin import get_current_user
from shared.settings_service import (
    get_settings_service,
    SettingNotFoundError,
    SettingValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/settings", tags=["settings"])


# =============================================================================
# Pydantic Models
# =============================================================================


class SettingResponse(BaseModel):
    """Response model for a single setting."""
    id: str
    key: str
    value: Any
    value_type: str
    default_value: Any
    min_value: Any | None = None
    max_value: Any | None = None
    allowed_values: list[str] | None = None
    label: str
    description: str | None = None
    requires_restart: bool
    display_order: int
    updated_at: str | None = None
    updated_by: str | None = None


class SettingsByCategoryResponse(BaseModel):
    """Response model for all settings grouped by category."""
    categories: dict[str, list[SettingResponse]]


class UpdateSettingRequest(BaseModel):
    """Request model for updating a setting."""
    value: Any = Field(..., description="New value for the setting")
    reason: str | None = Field(None, description="Optional reason for the change")


class HistoryEntryResponse(BaseModel):
    """Response model for a history entry."""
    id: str
    setting_key: str
    previous_value: Any | None
    new_value: Any
    changed_by: str
    change_reason: str | None = None
    changed_at: str


class HistoryResponse(BaseModel):
    """Response model for settings history."""
    entries: list[HistoryEntryResponse]
    total: int


class WorkerRestartResponse(BaseModel):
    """Response model for worker restart."""
    success: bool
    message: str


# =============================================================================
# Settings Endpoints
# =============================================================================


@router.get("", response_model=SettingsByCategoryResponse)
async def get_all_settings(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> SettingsByCategoryResponse:
    """
    Get all system settings grouped by category.

    Returns settings organized by category with full metadata.
    Used by admin panel to render the settings page.
    """
    service = await get_settings_service()
    grouped = await service.get_all()

    return SettingsByCategoryResponse(
        categories={
            category: [SettingResponse(**s) for s in settings]
            for category, settings in grouped.items()
        }
    )


@router.get("/history", response_model=HistoryResponse)
async def get_settings_history(
    current_user: Annotated[dict, Depends(get_current_user)],
    key: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HistoryResponse:
    """
    Get settings change history.

    Optional filter by setting key. Paginated results.
    """
    service = await get_settings_service()
    entries = await service.get_history(key=key, limit=limit, offset=offset)

    return HistoryResponse(
        entries=[HistoryEntryResponse(**e) for e in entries],
        total=len(entries),
    )


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> SettingResponse:
    """
    Get a single setting by key.

    Returns full setting details including metadata and validation rules.
    """
    service = await get_settings_service()
    setting = await service.get_setting(key)

    if setting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting not found: {key}"
        )

    # Convert to response format
    typed_value = service._convert_value(setting.value, setting.value_type)

    return SettingResponse(
        id=str(setting.id),
        key=setting.key,
        value=typed_value,
        value_type=setting.value_type,
        default_value=service._convert_value(setting.default_value, setting.value_type),
        min_value=setting.min_value,
        max_value=setting.max_value,
        allowed_values=setting.allowed_values,
        label=setting.label,
        description=setting.description,
        requires_restart=setting.requires_restart,
        display_order=setting.display_order,
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
        updated_by=setting.updated_by,
    )


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    request: UpdateSettingRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> SettingResponse:
    """
    Update a setting value.

    Validates the value against the setting's constraints (type, range, enum).
    Creates an audit trail entry with the change.
    """
    service = await get_settings_service()

    try:
        # Get username from current user
        username = current_user.get("username", "unknown")

        setting = await service.update(
            key=key,
            value=request.value,
            changed_by=username,
            change_reason=request.reason,
        )

        # Convert to response
        typed_value = service._convert_value(setting.value, setting.value_type)

        return SettingResponse(
            id=str(setting.id),
            key=setting.key,
            value=typed_value,
            value_type=setting.value_type,
            default_value=service._convert_value(setting.default_value, setting.value_type),
            min_value=setting.min_value,
            max_value=setting.max_value,
            allowed_values=setting.allowed_values,
            label=setting.label,
            description=setting.description,
            requires_restart=setting.requires_restart,
            display_order=setting.display_order,
            updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
            updated_by=setting.updated_by,
        )

    except SettingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting not found: {key}"
        )
    except SettingValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{key}/reset", response_model=SettingResponse)
async def reset_setting_to_default(
    key: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> SettingResponse:
    """
    Reset a setting to its default value.

    Creates an audit trail entry for the reset.
    """
    service = await get_settings_service()

    try:
        username = current_user.get("username", "unknown")
        setting = await service.reset_to_default(key, changed_by=username)

        typed_value = service._convert_value(setting.value, setting.value_type)

        return SettingResponse(
            id=str(setting.id),
            key=setting.key,
            value=typed_value,
            value_type=setting.value_type,
            default_value=service._convert_value(setting.default_value, setting.value_type),
            min_value=setting.min_value,
            max_value=setting.max_value,
            allowed_values=setting.allowed_values,
            label=setting.label,
            description=setting.description,
            requires_restart=setting.requires_restart,
            display_order=setting.display_order,
            updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
            updated_by=setting.updated_by,
        )

    except SettingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting not found: {key}"
        )


DOCKER_SOCKET = "/var/run/docker.sock"
CONFIRMATION_WORKER_CONTAINER = "atrevete-confirmation-worker"


@router.post("/restart-worker", response_model=WorkerRestartResponse)
async def restart_confirmation_worker(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> WorkerRestartResponse:
    """
    Restart the confirmation worker container.

    Required after changing settings that require restart
    (job times, intervals, etc.).

    Uses Docker Engine API via unix socket. May take up to 30 seconds.
    """
    try:
        logger.info(
            f"Worker restart requested by {current_user.get('username', 'unknown')}"
        )

        # Docker Engine API via unix socket (async)
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.post(
                f"/v1.44/containers/{CONFIRMATION_WORKER_CONTAINER}/restart",
                timeout=60.0,
            )

        if response.status_code == 204:
            logger.info("Confirmation worker restarted successfully")
            return WorkerRestartResponse(
                success=True,
                message="Worker de confirmaciones reiniciado correctamente"
            )
        elif response.status_code == 404:
            logger.error(f"Container not found: {CONFIRMATION_WORKER_CONTAINER}")
            return WorkerRestartResponse(
                success=False,
                message=f"Contenedor '{CONFIRMATION_WORKER_CONTAINER}' no encontrado"
            )
        else:
            logger.error(f"Docker API error: {response.status_code} - {response.text}")
            return WorkerRestartResponse(
                success=False,
                message=f"Error Docker API: {response.status_code}"
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Docker daemon")
        return WorkerRestartResponse(
            success=False,
            message="No se puede conectar al Docker daemon. Verifica que el socket esté montado."
        )
    except httpx.TimeoutException:
        logger.error("Worker restart timed out")
        return WorkerRestartResponse(
            success=False,
            message="Timeout al reiniciar worker (>60s)"
        )
    except Exception as e:
        logger.error(f"Worker restart error: {e}")
        return WorkerRestartResponse(
            success=False,
            message=f"Error inesperado: {str(e)}"
        )
