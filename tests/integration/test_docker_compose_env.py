"""T6 — I2: Assert all runtime services declare env_file: .env in docker-compose.yml.

Spec: REQ-I2 / SC-I2-A, SC-I2-B, SC-I2-D, SC-I2-E

This is a regression guard: if someone removes env_file from a service, the
TEST_MODE_GCAL_SKIP and TEST_PHONE_PREFIX variables will silently stop reaching
that container. This test prevents silent propagation breaks.

env_file is the single source of truth for runtime env vars (ADR-I2.1).
The actual values (TEST_MODE_GCAL_SKIP=true, TEST_PHONE_PREFIX=+34999) are
set in the server .env file and NOT committed to the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"

# All runtime services that process requests or run the agent must have
# env_file: .env so that TEST_MODE_GCAL_SKIP and TEST_PHONE_PREFIX propagate.
REQUIRED_ENV_FILE_SERVICES = {
    "api",
    "agent",
    "archiver",
    "gcal-sync-worker",
    "billing-worker",
    "notifications",
}

EXPECTED_ENV_FILE = ".env"


@pytest.fixture(scope="module")
def compose_data() -> dict:
    assert COMPOSE_PATH.exists(), f"docker-compose.yml not found at {COMPOSE_PATH}"
    with open(COMPOSE_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "docker-compose.yml must parse to a dict"
    return data


def test_docker_compose_file_exists() -> None:
    assert COMPOSE_PATH.exists(), f"docker-compose.yml not found at {COMPOSE_PATH}"


def test_docker_compose_parses() -> None:
    with open(COMPOSE_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data is not None
    assert "services" in data


@pytest.mark.parametrize("service_name", sorted(REQUIRED_ENV_FILE_SERVICES))
def test_service_declares_env_file(service_name: str, compose_data: dict) -> None:
    """SC-I2-A/B/D: Each runtime service must declare env_file: .env.

    This ensures TEST_MODE_GCAL_SKIP and TEST_PHONE_PREFIX reach the container.
    env_file is ONLY re-read at container creation time (not on restart), so
    --force-recreate is required when the .env file changes.
    """
    services = compose_data.get("services", {})
    assert service_name in services, (
        f"Service '{service_name}' not found in docker-compose.yml services. "
        "If it was renamed or removed, update REQUIRED_ENV_FILE_SERVICES."
    )
    service_def = services[service_name]
    env_file = service_def.get("env_file")

    if env_file is None:
        pytest.fail(
            f"Service '{service_name}' has no 'env_file' key in docker-compose.yml. "
            f"Add 'env_file: {EXPECTED_ENV_FILE}' to ensure TEST_MODE_GCAL_SKIP "
            f"and TEST_PHONE_PREFIX reach the container."
        )

    # env_file can be a string or a list
    if isinstance(env_file, str):
        env_files = [env_file]
    elif isinstance(env_file, list):
        env_files = env_file
    else:
        pytest.fail(
            f"Service '{service_name}' env_file has unexpected type {type(env_file)}. "
            f"Expected str or list."
        )

    assert EXPECTED_ENV_FILE in env_files, (
        f"Service '{service_name}' env_file does not include '{EXPECTED_ENV_FILE}'. "
        f"Found: {env_files}. "
        f"Add '{EXPECTED_ENV_FILE}' to ensure TEST_MODE_GCAL_SKIP propagates."
    )
