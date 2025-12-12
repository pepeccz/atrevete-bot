"""
System Management API Endpoints for Admin Panel

Provides REST endpoints for:
- GET /api/admin/system/services - List all services with status
- GET /api/admin/system/{service}/logs - Stream logs (SSE)
- POST /api/admin/system/{service}/restart - Restart service
- POST /api/admin/system/{service}/stop - Stop service
"""

import asyncio
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.routes.admin import get_current_user, verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/system", tags=["system"])

# Docker socket path
DOCKER_SOCKET = "/var/run/docker.sock"

# Service to container name mapping
CONTAINER_MAP = {
    "api": "atrevete-api",
    "agent": "atrevete-agent",
    "archiver": "atrevete-archiver",
    "confirmation-worker": "atrevete-confirmation-worker",
    "gcal-sync-worker": "atrevete-gcal-sync-worker",
    "postgres": "atrevete-postgres",
    "redis": "atrevete-redis",
}

# Services that can be controlled (excluding admin-panel)
CONTROLLABLE_SERVICES = list(CONTAINER_MAP.keys())


# =============================================================================
# Pydantic Models
# =============================================================================


class ServiceStatus(BaseModel):
    """Status of a single service."""
    name: str
    container: str
    status: str  # running, exited, paused, etc.
    health: str | None = None  # healthy, unhealthy, starting, none


class ServicesResponse(BaseModel):
    """Response with all services status."""
    services: list[ServiceStatus]


class ServiceActionResponse(BaseModel):
    """Response for service actions (restart/stop)."""
    success: bool
    message: str


# =============================================================================
# Helper Functions
# =============================================================================


async def get_container_status(container_name: str) -> dict:
    """Get container status via Docker API."""
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.get(
                f"/v1.44/containers/{container_name}/json",
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                state = data.get("State", {})
                health = state.get("Health", {}).get("Status") if "Health" in state else None
                return {
                    "status": state.get("Status", "unknown"),
                    "health": health,
                }
            elif response.status_code == 404:
                return {"status": "not_found", "health": None}
            else:
                return {"status": "error", "health": None}
    except Exception as e:
        logger.error(f"Error getting container status for {container_name}: {e}")
        return {"status": "error", "health": None}


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/services", response_model=ServicesResponse)
async def list_services(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ServicesResponse:
    """
    List all services with their current status.

    Returns container status and health for each service.
    """
    services = []

    # Fetch status for all containers in parallel
    tasks = [
        get_container_status(container)
        for container in CONTAINER_MAP.values()
    ]
    results = await asyncio.gather(*tasks)

    for (service_name, container_name), status_info in zip(CONTAINER_MAP.items(), results):
        services.append(ServiceStatus(
            name=service_name,
            container=container_name,
            status=status_info["status"],
            health=status_info["health"],
        ))

    return ServicesResponse(services=services)


@router.get("/{service}/logs")
async def stream_logs(
    service: str,
    tail: int = 100,
    token: str | None = None,
):
    """
    Stream logs from a service container using Server-Sent Events (SSE).

    Uses Docker API to stream logs in real-time.

    Note: Accepts token as query param because EventSource doesn't support headers.
    """
    # Verify authentication via query param (EventSource doesn't support headers)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token required for log streaming",
        )

    try:
        payload = verify_token(token)
        username = payload.get("sub", "unknown")
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if service not in CONTAINER_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service not found: {service}. Available: {list(CONTAINER_MAP.keys())}"
        )

    container_name = CONTAINER_MAP[service]
    logger.info(f"Starting log stream for {container_name} requested by {username}")

    async def generate_logs():
        """Generator that streams Docker logs via Docker API."""
        try:
            transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
            async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
                # Docker logs API with follow and tail
                async with client.stream(
                    "GET",
                    f"/v1.44/containers/{container_name}/logs",
                    params={
                        "follow": "true",
                        "stdout": "true",
                        "stderr": "true",
                        "tail": str(tail),
                        "timestamps": "true",
                    },
                    timeout=None,  # No timeout for streaming
                ) as response:
                    if response.status_code != 200:
                        yield f"data: Error: {response.status_code}\n\n"
                        return

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            # Docker logs have 8-byte header per frame
                            # Skip header and decode the rest
                            try:
                                # Process each frame in the chunk
                                offset = 0
                                while offset < len(chunk):
                                    if offset + 8 > len(chunk):
                                        break
                                    # Header: 1 byte stream type, 3 bytes padding, 4 bytes size
                                    size = int.from_bytes(chunk[offset+4:offset+8], 'big')
                                    if offset + 8 + size > len(chunk):
                                        # Partial frame, skip
                                        break
                                    frame_data = chunk[offset+8:offset+8+size]
                                    line = frame_data.decode('utf-8', errors='replace').strip()
                                    if line:
                                        # Escape newlines for SSE
                                        escaped_line = line.replace('\n', '\\n')
                                        yield f"data: {escaped_line}\n\n"
                                    offset += 8 + size
                            except Exception as e:
                                # Fallback: try to decode entire chunk
                                try:
                                    text = chunk.decode('utf-8', errors='replace').strip()
                                    if text:
                                        yield f"data: {text}\n\n"
                                except:
                                    pass
        except httpx.ConnectError:
            yield "data: Error: Cannot connect to Docker daemon\n\n"
        except Exception as e:
            logger.error(f"Log streaming error: {e}")
            yield f"data: Error: {str(e)}\n\n"

    return StreamingResponse(
        generate_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/{service}/restart", response_model=ServiceActionResponse)
async def restart_service(
    service: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ServiceActionResponse:
    """
    Restart a service container.

    Uses Docker API to restart the container.
    """
    if service not in CONTROLLABLE_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service not found: {service}. Available: {CONTROLLABLE_SERVICES}"
        )

    container_name = CONTAINER_MAP[service]
    username = current_user.get("username", "unknown")
    logger.info(f"Service restart requested: {container_name} by {username}")

    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.post(
                f"/v1.44/containers/{container_name}/restart",
                timeout=60.0,
            )

        if response.status_code == 204:
            logger.info(f"Service {container_name} restarted successfully")
            return ServiceActionResponse(
                success=True,
                message=f"Servicio '{service}' reiniciado correctamente"
            )
        elif response.status_code == 404:
            logger.error(f"Container not found: {container_name}")
            return ServiceActionResponse(
                success=False,
                message=f"Contenedor '{container_name}' no encontrado"
            )
        else:
            error_detail = response.text
            logger.error(f"Docker API error: {response.status_code} - {error_detail}")
            return ServiceActionResponse(
                success=False,
                message=f"Error Docker API: {response.status_code}"
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Docker daemon")
        return ServiceActionResponse(
            success=False,
            message="No se puede conectar al Docker daemon"
        )
    except httpx.TimeoutException:
        logger.error("Service restart timed out")
        return ServiceActionResponse(
            success=False,
            message="Timeout al reiniciar servicio (>60s)"
        )
    except Exception as e:
        logger.error(f"Service restart error: {e}")
        return ServiceActionResponse(
            success=False,
            message=f"Error inesperado: {str(e)}"
        )


@router.post("/{service}/stop", response_model=ServiceActionResponse)
async def stop_service(
    service: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ServiceActionResponse:
    """
    Stop a service container.

    Uses Docker API to stop the container.
    WARNING: This will stop the service until manually restarted.
    """
    if service not in CONTROLLABLE_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service not found: {service}. Available: {CONTROLLABLE_SERVICES}"
        )

    # Extra protection: don't allow stopping critical services easily
    if service == "api":
        return ServiceActionResponse(
            success=False,
            message="No se puede detener la API desde el panel (se perderia la conexion)"
        )

    container_name = CONTAINER_MAP[service]
    username = current_user.get("username", "unknown")
    logger.warning(f"Service STOP requested: {container_name} by {username}")

    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.post(
                f"/v1.44/containers/{container_name}/stop",
                timeout=30.0,
            )

        if response.status_code == 204:
            logger.info(f"Service {container_name} stopped successfully")
            return ServiceActionResponse(
                success=True,
                message=f"Servicio '{service}' detenido correctamente"
            )
        elif response.status_code == 304:
            return ServiceActionResponse(
                success=True,
                message=f"Servicio '{service}' ya estaba detenido"
            )
        elif response.status_code == 404:
            logger.error(f"Container not found: {container_name}")
            return ServiceActionResponse(
                success=False,
                message=f"Contenedor '{container_name}' no encontrado"
            )
        else:
            error_detail = response.text
            logger.error(f"Docker API error: {response.status_code} - {error_detail}")
            return ServiceActionResponse(
                success=False,
                message=f"Error Docker API: {response.status_code}"
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Docker daemon")
        return ServiceActionResponse(
            success=False,
            message="No se puede conectar al Docker daemon"
        )
    except httpx.TimeoutException:
        logger.error("Service stop timed out")
        return ServiceActionResponse(
            success=False,
            message="Timeout al detener servicio (>30s)"
        )
    except Exception as e:
        logger.error(f"Service stop error: {e}")
        return ServiceActionResponse(
            success=False,
            message=f"Error inesperado: {str(e)}"
        )


@router.post("/gcal-sync/trigger", response_model=ServiceActionResponse)
async def trigger_gcal_sync(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ServiceActionResponse:
    """
    Manually trigger Google Calendar sync.

    Imports and runs the sync function directly for immediate execution.
    """
    username = current_user.get("username", "unknown")
    logger.info(f"Manual GCal sync triggered by {username}")

    try:
        # Import and run the sync function
        from agent.workers.gcal_sync_worker import run_gcal_sync

        await run_gcal_sync()

        return ServiceActionResponse(
            success=True,
            message="Sincronización con Google Calendar completada"
        )

    except Exception as e:
        logger.error(f"Manual GCal sync error: {e}", exc_info=True)
        return ServiceActionResponse(
            success=False,
            message=f"Error en la sincronización: {str(e)}"
        )
