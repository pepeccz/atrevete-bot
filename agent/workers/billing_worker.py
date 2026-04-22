"""
Billing worker — Monthly invoice generation and overdue checks.

This worker handles two scheduled jobs:
1. run_monthly_invoice (02:00 daily): Generates invoice on the 1st of each month
2. run_overdue_check (03:00 daily): Marks overdue invoices and logs the count

Architecture:
    - Runs daily jobs at fixed times in Europe/Madrid timezone
    - Skips invoice generation on any day other than the 1st
    - Uses health check monitoring compatible with Docker healthcheck
    - Implements graceful shutdown via SIGTERM/SIGINT
"""

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from api.services.billing_service import BillingService
from database.connection import get_async_session

# Configure logger
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False

# Timezone for all datetime operations
MADRID_TZ = ZoneInfo("Europe/Madrid")

# Job schedule times (HH:MM)
INVOICE_JOB_TIME = "02:00"
OVERDUE_JOB_TIME = "03:00"

# Singleton billing service instance
_billing_service = BillingService()


def signal_handler(signum: int, frame: Any) -> None:
    """
    Handle SIGTERM/SIGINT for graceful shutdown.
    """
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# =============================================================================
# Health Check
# =============================================================================


async def update_health_check(
    job_name: str,
    last_run: datetime,
    status: str,
    processed: int,
    errors: int,
) -> None:
    """
    Update health check file with job statistics.

    Args:
        job_name: Name of the job
        last_run: Timestamp of job completion
        status: Health status ('healthy' or 'unhealthy')
        processed: Number of items processed
        errors: Number of errors encountered
    """
    health_dir = Path("/tmp/health")
    health_dir.mkdir(parents=True, exist_ok=True)
    health_file = health_dir / "billing_worker_health.json"
    temp_file = health_dir / f"billing_worker_health.{int(time.time())}.tmp"

    # Load existing health data
    health_data: dict[str, Any] = {}
    if health_file.exists():
        try:
            health_data = json.loads(health_file.read_text())
        except Exception:
            pass

    # Update job status
    health_data[job_name] = {
        "last_run": last_run.isoformat(),
        "status": status,
        "processed": processed,
        "errors": errors,
    }

    # Update overall status
    all_healthy = all(
        job.get("status") == "healthy" for job in health_data.values() if isinstance(job, dict)
    )
    health_data["overall_status"] = "healthy" if all_healthy else "unhealthy"
    health_data["last_updated"] = datetime.now(MADRID_TZ).isoformat()
    health_data["last_heartbeat"] = time.time()

    try:
        with open(temp_file, "w", encoding="utf-8") as health_handle:
            json.dump(health_data, health_handle, indent=2)
        temp_file.rename(health_file)
        logger.debug(f"Health check file updated: {health_file}")
    except Exception as e:
        logger.error(f"Failed to write health check file: {e}", exc_info=True)


# =============================================================================
# Job 1: Monthly Invoice Generation
# =============================================================================


async def run_monthly_invoice() -> None:
    """
    Generate the monthly invoice for the previous billing period.

    Only executes on the 1st day of the month. Skips silently on all other days.
    Handles duplicate generation gracefully (IntegrityError / 409).
    """
    now = datetime.now(MADRID_TZ)

    if now.day != 1:
        logger.debug(f"Skipping invoice generation — today is day {now.day}, not the 1st")
        return

    # Calculate previous month (handle January → December edge case)
    if now.month == 1:
        prev_year = now.year - 1
        prev_month = 12
    else:
        prev_year = now.year
        prev_month = now.month - 1

    logger.info(f"Running monthly invoice generation for {prev_year}-{prev_month:02d}")

    errors = 0
    try:
        async with get_async_session() as session:
            invoice = await _billing_service.generate_invoice(session, prev_year, prev_month)
            logger.info(
                f"Invoice generated successfully: id={invoice.id}, "
                f"period={prev_year}-{prev_month:02d}"
            )
    except IntegrityError:
        logger.info(f"Invoice already exists for {prev_year}-{prev_month:02d}, skipping")
    except HTTPException as exc:
        if exc.status_code == 409:
            logger.info(f"Invoice already exists for {prev_year}-{prev_month:02d} (409), skipping")
        else:
            logger.error(
                f"HTTP error generating invoice for {prev_year}-{prev_month:02d}: "
                f"status={exc.status_code} detail={exc.detail}",
                exc_info=True,
            )
            errors += 1
    except Exception:
        logger.error(
            f"Unexpected error generating invoice for {prev_year}-{prev_month:02d}",
            exc_info=True,
        )
        errors += 1

    await update_health_check(
        job_name="run_monthly_invoice",
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if errors == 0 else "unhealthy",
        processed=1 if errors == 0 else 0,
        errors=errors,
    )


# =============================================================================
# Job 2: Overdue Check
# =============================================================================


async def run_overdue_check() -> None:
    """
    Check for overdue invoices and log the newly-overdue count.
    """
    now = datetime.now(MADRID_TZ)
    logger.info(f"Running overdue check at {now.isoformat()}")

    errors = 0
    newly_overdue = 0
    try:
        async with get_async_session() as session:
            newly_overdue = await _billing_service.check_overdue(session)
            logger.info(f"Overdue check completed — newly overdue invoices: {newly_overdue}")
    except Exception:
        logger.error("Unexpected error in overdue check", exc_info=True)
        errors += 1

    await update_health_check(
        job_name="run_overdue_check",
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if errors == 0 else "unhealthy",
        processed=newly_overdue,
        errors=errors,
    )


# =============================================================================
# Heartbeat
# =============================================================================


async def _heartbeat_loop() -> None:
    """
    Background heartbeat task to keep health check fresh during idle periods.

    Runs every 60 seconds while the worker is alive, ensuring the health check
    file is updated even when no jobs are executing.
    """
    while not shutdown_requested:
        try:
            await update_health_check(
                job_name="heartbeat",
                last_run=datetime.now(MADRID_TZ),
                status="healthy",
                processed=0,
                errors=0,
            )
        except Exception as e:
            logger.warning(f"Error updating heartbeat: {e}")

        await asyncio.sleep(60)


# =============================================================================
# Main Entry Point
# =============================================================================


async def async_main() -> None:
    """
    Main async entry point — runs billing jobs on schedule using a single event loop.

    IMPORTANT: Uses asyncio.sleep() instead of schedule + asyncio.run() to avoid
    event loop corruption. Each asyncio.run() creates a new event loop, but
    SQLAlchemy's asyncpg connections keep references to the previous loop,
    causing "Future attached to a different loop" errors.

    Schedule:
    - run_monthly_invoice: Daily at 02:00 Europe/Madrid (runs only on the 1st)
    - run_overdue_check: Daily at 03:00 Europe/Madrid

    Handles graceful shutdown on SIGTERM/SIGINT.
    """
    logger.info("Billing worker starting...")
    logger.info(
        f"Schedule: invoice={INVOICE_JOB_TIME}, overdue={OVERDUE_JOB_TIME}, "
        f"TIMEZONE={MADRID_TZ}"
    )

    # Write initial health check file
    await update_health_check(
        job_name="startup",
        last_run=datetime.now(MADRID_TZ),
        status="healthy",
        processed=0,
        errors=0,
    )
    logger.info("Initial health check file written")

    # Launch background heartbeat task to keep health check fresh during idle
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info("Background heartbeat task started")

    # Track last execution dates to avoid running jobs multiple times per day
    last_invoice_run: str | None = None  # Format: "YYYY-MM-DD"
    last_overdue_run: str | None = None  # Format: "YYYY-MM-DD"

    # Main loop — check every minute
    while not shutdown_requested:
        now = datetime.now(MADRID_TZ)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if current_time == INVOICE_JOB_TIME and last_invoice_run != current_date:
            logger.info(f"Running run_monthly_invoice at {current_time}")
            try:
                await run_monthly_invoice()
            except Exception as e:
                logger.error(f"Error in run_monthly_invoice: {e}", exc_info=True)
            last_invoice_run = current_date

        if current_time == OVERDUE_JOB_TIME and last_overdue_run != current_date:
            logger.info(f"Running run_overdue_check at {current_time}")
            try:
                await run_overdue_check()
            except Exception as e:
                logger.error(f"Error in run_overdue_check: {e}", exc_info=True)
            last_overdue_run = current_date

        # Sleep for 1 minute before checking again
        await asyncio.sleep(60)

    # Cancel heartbeat task on shutdown
    logger.info("Shutting down background heartbeat task...")
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    logger.info("Billing worker shutting down gracefully...")


def run_billing_worker() -> None:
    """
    Synchronous entry point that sets up logging and signal handlers,
    then runs the async main function.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Run the async main with a single event loop
    asyncio.run(async_main())


if __name__ == "__main__":
    run_billing_worker()
