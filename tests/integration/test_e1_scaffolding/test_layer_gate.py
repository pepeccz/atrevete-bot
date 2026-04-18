"""Integration tests for scripts/check_layers.py (R16, R17).

The gate enforces layer dependency rules defined in docs/system/02-layers.md.
In E1, `cores/` and `modulos/` do NOT exist yet → gate exits 0 (no rules to enforce).
Substantive violation detection is tested via synthetic temp trees (--self-test behaviour
is also tested via the dedicated flag).

All subprocess calls use `sys.executable` to ensure the same interpreter as pytest.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # …/atrevete-bot
SCRIPT = REPO_ROOT / "scripts" / "check_layers.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# R16 — violation detection
# ---------------------------------------------------------------------------


def test_subprocess_violation_returns_exit_1(tmp_path: Path) -> None:
    """A modulos/* file that imports from another modulos/* → exit 1 + violation in output."""
    # Build synthetic tree: modulos/booking and modulos/appointment_mgmt
    (tmp_path / "modulos" / "booking").mkdir(parents=True)
    (tmp_path / "modulos" / "appointment_mgmt").mkdir(parents=True)

    # Create package markers
    (tmp_path / "modulos" / "__init__.py").write_text("")
    (tmp_path / "modulos" / "booking" / "__init__.py").write_text("")
    (tmp_path / "modulos" / "appointment_mgmt" / "__init__.py").write_text("")

    # Violating file: booking imports from appointment_mgmt (sibling module)
    (tmp_path / "modulos" / "booking" / "service.py").write_text(
        "from modulos.appointment_mgmt import something\n"
    )

    result = _run([str(tmp_path)])

    assert result.returncode == 1, (
        f"Expected exit 1 for violation. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Violation path must appear in output
    assert "modulos" in result.stdout or "modulos" in result.stderr, (
        f"Expected violation path in output. stdout={result.stdout!r}"
    )


def test_subprocess_clean_returns_exit_0(tmp_path: Path) -> None:
    """A compliant modulos/* structure (no cross-module imports) → exit 0."""
    (tmp_path / "modulos" / "booking").mkdir(parents=True)
    (tmp_path / "modulos" / "__init__.py").write_text("")
    (tmp_path / "modulos" / "booking" / "__init__.py").write_text("")
    # Only imports from cores and infra — no sibling module imports
    (tmp_path / "modulos" / "booking" / "service.py").write_text(
        "from cores.appointments import Appointment\n"
        "from infra.database import session\n"
    )

    result = _run([str(tmp_path)])

    assert result.returncode == 0, (
        f"Expected exit 0 for clean tree. stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# R16 — current repo root exits 0 (cores/ and modulos/ absent in E1)
# ---------------------------------------------------------------------------


def test_current_repo_root_returns_exit_0() -> None:
    """Running gate against actual repo root → exit 0 (no cores/modulos dirs in E1)."""
    # Verify the dirs are indeed absent before testing
    assert not (REPO_ROOT / "cores").exists(), "cores/ must not exist in E1"
    assert not (REPO_ROOT / "modulos").exists(), "modulos/ must not exist in E1"

    result = _run([str(REPO_ROOT)])

    assert result.returncode == 0, (
        f"Expected exit 0 on repo root (no layer dirs). "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# R17 — --self-test flag
# ---------------------------------------------------------------------------


def test_self_test_flag_returns_exit_0() -> None:
    """--self-test exercises the gate internally and exits 0 if internal checks pass."""
    result = _run(["--self-test"])

    assert result.returncode == 0, (
        f"Expected exit 0 from --self-test. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
