"""T9.a RED — pytest-recording importable; T9.b — vcr_config fixture present.

R-IDs: R12
"""
from __future__ import annotations

import pytest


def test_pytest_recording_importable() -> None:
    """pytest-recording must be installed."""
    import pytest_recording  # noqa: F401


def test_vcr_config_fixture_exists(pytestconfig: pytest.Config) -> None:
    """vcr_config fixture must be registered (via conftest)."""
    # We verify the fixture is available by checking it appears in the fixture list
    fixtures = pytestconfig.pluginmanager.get_plugin("funcmanage")
    # Simpler: just try to collect it
    import importlib.util

    conftest_path = pytestconfig.rootpath / "tests" / "integration" / "conftest.py"
    assert conftest_path.exists(), "tests/integration/conftest.py must exist"
    spec = importlib.util.spec_from_file_location("conftest_integration", conftest_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "vcr_config"), (
        "tests/integration/conftest.py must define a vcr_config fixture"
    )
