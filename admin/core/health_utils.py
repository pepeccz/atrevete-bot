"""
Health check utilities for infrastructure status dashboard.

Provides functions to query the health and status of:
- Docker containers
- Redis
- PostgreSQL
- Archiver worker
- Recent activity and metrics
"""

import asyncio
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.db import connection
from django.db.models import Count
from django.utils import timezone

from .models import Appointment, ConversationHistory, Customer


# ============================================================================
# Docker Status
# ============================================================================


def get_docker_status() -> list[dict[str, Any]]:
    """
    Query Docker API for container status.

    Returns a list of containers with their status, health check status, and state.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    container = json.loads(line)
                    containers.append(
                        {
                            "name": container.get("Names", "unknown"),
                            "image": container.get("Image", "unknown"),
                            "status": container.get("Status", "unknown"),
                            "health": parse_health_status(container.get("Status", "")),
                            "state": container.get("State", "unknown"),
                        }
                    )
                except json.JSONDecodeError:
                    continue

        return sorted(containers, key=lambda x: x["name"])
    except Exception as e:
        return [{"error": str(e), "name": "error"}]


def parse_health_status(status_str: str) -> str:
    """
    Parse Docker health status from status string.

    Examples:
        "Up 2 days (healthy)" -> "healthy"
        "Up 2 days (unhealthy)" -> "unhealthy"
        "Up 2 days" -> "running"
        "Exited (0) 1 hour ago" -> "stopped"
    """
    if "(healthy)" in status_str:
        return "healthy"
    elif "(unhealthy)" in status_str:
        return "unhealthy"
    elif "Up" in status_str:
        return "running"
    elif "Exited" in status_str:
        return "stopped"
    else:
        return "unknown"


# ============================================================================
# Redis Health
# ============================================================================


def get_redis_health() -> dict[str, Any]:
    """
    Check Redis connectivity and basic statistics.

    Returns:
        Dict with connection status, uptime, memory usage, client count, key count.
    """
    try:
        from shared.redis_client import get_redis_client

        client = get_redis_client()

        # Run async operations in event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            ping_result = loop.run_until_complete(client.ping())
            if not ping_result:
                return {"status": "disconnected", "error": "PING returned False"}

            info = loop.run_until_complete(client.info())
            dbsize = loop.run_until_complete(client.dbsize())

            return {
                "status": "connected",
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "total_keys": dbsize,
                "version": info.get("redis_version", "unknown"),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


# ============================================================================
# PostgreSQL Health
# ============================================================================


def get_postgres_health() -> dict[str, Any]:
    """
    Check PostgreSQL connectivity and basic statistics.

    Returns:
        Dict with connection status, version, database size, active connections.
    """
    try:
        with connection.cursor() as cursor:
            # Get version
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]

            # Get database size
            cursor.execute("SELECT pg_database_size(current_database());")
            db_size_bytes = cursor.fetchone()[0]

            # Get active connections
            cursor.execute("SELECT count(*) FROM pg_stat_activity;")
            active_connections = cursor.fetchone()[0]

            # Get table counts
            cursor.execute(
                """
                SELECT count(*) FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            table_count = cursor.fetchone()[0]

        return {
            "status": "connected",
            "version": version.split(",")[0].split(" ")[1],
            "database_size_mb": round(db_size_bytes / (1024 * 1024), 2),
            "active_connections": active_connections,
            "table_count": table_count,
        }
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


# ============================================================================
# Archiver Worker Health
# ============================================================================


def get_archiver_health() -> dict[str, Any]:
    """
    Read archiver worker health from status file.

    The archiver worker writes health status to /tmp/archiver_health.json
    every time it runs (every 5 minutes).

    Returns:
        Dict with last run time, status, archived counts, and staleness indicator.
    """
    health_file = Path("/var/health/archiver_health.json")

    try:
        if not health_file.exists():
            return {"status": "unknown", "error": "Health file not found"}

        data = json.loads(health_file.read_text())

        # Parse last_run timestamp
        last_run = datetime.fromisoformat(data.get("last_run", ""))
        time_since = timezone.now() - last_run

        data["time_since_last_run_seconds"] = int(time_since.total_seconds())
        data["is_stale"] = time_since > timedelta(hours=1)

        return data
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON in health file",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# Recent Activity
# ============================================================================


def get_recent_activity() -> dict[str, Any]:
    """
    Query recent conversation and booking activity (last 24 hours).

    Returns:
        Dict with conversation count, message count, bookings, new customers.
    """
    try:
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)

        # Conversations (unique conversation_ids)
        conversations_24h = (
            ConversationHistory.objects.filter(timestamp__gte=last_24h)
            .values("conversation_id")
            .distinct()
            .count()
        )

        # Messages
        messages_24h = ConversationHistory.objects.filter(
            timestamp__gte=last_24h
        ).count()

        # Bookings
        bookings_24h = Appointment.objects.filter(created_at__gte=last_24h).count()

        # New customers
        new_customers_24h = Customer.objects.filter(
            created_at__gte=last_24h
        ).count()

        # Active conversations (last hour)
        active_conversations = (
            ConversationHistory.objects.filter(timestamp__gte=now - timedelta(hours=1))
            .values("conversation_id")
            .distinct()
            .count()
        )

        # Total customers and appointments
        total_customers = Customer.objects.count()
        total_appointments = Appointment.objects.count()

        # Average messages per conversation (last 7 days)
        conversations_7d = (
            ConversationHistory.objects.filter(timestamp__gte=last_7d)
            .values("conversation_id")
            .annotate(msg_count=Count("id"))
        )

        avg_messages_per_conversation = 0.0
        if conversations_7d.exists():
            total_messages = sum(c["msg_count"] for c in conversations_7d)
            avg_messages_per_conversation = round(
                total_messages / conversations_7d.count(), 1
            )

        return {
            "conversations_24h": conversations_24h,
            "messages_24h": messages_24h,
            "bookings_24h": bookings_24h,
            "new_customers_24h": new_customers_24h,
            "active_conversations": active_conversations,
            "total_customers": total_customers,
            "total_appointments": total_appointments,
            "avg_messages_per_conversation": avg_messages_per_conversation,
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# System Status
# ============================================================================


def get_system_status(
    redis_health: dict[str, Any],
    postgres_health: dict[str, Any],
    archiver_health: dict[str, Any],
) -> str:
    """
    Calculate overall system health status.

    Returns:
        "healthy" if all critical systems operational
        "degraded" if some systems have issues
        "critical" if multiple systems are down
    """
    issues = 0

    if redis_health.get("status") != "connected":
        issues += 1

    if postgres_health.get("status") != "connected":
        issues += 1

    if archiver_health.get("status") not in ("healthy", "unknown"):
        issues += 1

    if archiver_health.get("is_stale"):
        issues += 0.5  # Minor issue

    if issues >= 2:
        return "critical"
    elif issues >= 1:
        return "degraded"
    else:
        return "healthy"


def get_status_color(status: str) -> str:
    """Get color for status badge."""
    colors = {
        "healthy": "success",
        "degraded": "warning",
        "critical": "danger",
        "connected": "success",
        "disconnected": "danger",
        "running": "success",
        "stopped": "danger",
        "unknown": "secondary",
    }
    return colors.get(status, "secondary")


def get_status_icon(status: str) -> str:
    """Get emoji/icon for status."""
    icons = {
        "healthy": "🟢",
        "degraded": "🟡",
        "critical": "🔴",
        "connected": "✅",
        "disconnected": "❌",
        "running": "🟢",
        "stopped": "🔴",
        "unknown": "⚪",
    }
    return icons.get(status, "")
