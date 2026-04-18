#!/usr/bin/env python3
"""AST-based layer import gate. See docs/system/02-layers.md for the dependency rules.

Exit codes: 0=clean, 1=violations, 2=parse-error or bad invocation.
Usage:
  python scripts/check_layers.py [root_dir]
  python scripts/check_layers.py --self-test
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

# (source_layer, forbidden_prefixes, allowed_exception_prefixes)
_RULES: list[tuple[str, list[str], list[str]]] = [
    ("cores",   ["modulos", "infra"], ["infra.config", "infra.observability"]),
    ("modulos", ["modulos"],          []),  # sibling modules forbidden
    ("infra",   ["modulos"],          []),
]

_SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "__pycache__", "venv", ".venv", "node_modules", "versions", ".tox", "dist", "build"}
)


def _layer(path: Path, root: Path) -> str | None:
    try:
        parts = path.relative_to(root).parts
        return parts[0] if parts else None
    except ValueError:
        return None


def _dotted(path: Path, root: Path) -> str:
    try:
        return ".".join(path.relative_to(root).with_suffix("").parts)
    except ValueError:
        return ""


def _forbidden(imported: str, source_layer: str, src_module: str) -> bool:
    for src, banned, allowed in _RULES:
        if src != source_layer:
            continue
        for fb in banned:
            if not (imported == fb or imported.startswith(fb + ".")):
                continue
            if any(imported == exc or imported.startswith(exc + ".") for exc in allowed):
                return False
            # modulos rule: same top-2 prefix → within same module, allowed
            if src == "modulos" == fb:
                src2 = ".".join(src_module.split(".")[:2])
                imp2 = ".".join(imported.split(".")[:2])
                if src2 == imp2:
                    return False
            return True
    return False


def scan(root: Path) -> tuple[list[str], bool]:
    violations: list[str] = []
    had_error = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            layer = _layer(fpath, root)
            if layer not in {"cores", "modulos", "infra"}:
                continue
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="replace"), filename=str(fpath))
            except SyntaxError as exc:
                print(f"[parse-error] {fpath}: {exc}", file=sys.stderr)
                had_error = True
                continue
            src_mod = _dotted(fpath, root)
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    targets = [node.module]
                for imp in targets:
                    if _forbidden(imp, layer, src_mod):
                        violations.append(
                            f"{fpath}:{getattr(node, 'lineno', '?')}: [{layer}] imports forbidden '{imp}'"
                        )
    return violations, had_error


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="check_layers_self_test_") as tmp:
        root = Path(tmp)

        # bad: modulos/booking imports sibling modulos/appointment_mgmt
        bad = root / "bad"
        for d in ("modulos/booking", "modulos/appointment_mgmt"):
            (bad / d).mkdir(parents=True)
        for d in ("modulos", "modulos/booking", "modulos/appointment_mgmt"):
            (bad / d / "__init__.py").write_text("")
        (bad / "modulos" / "booking" / "svc.py").write_text(
            "from modulos.appointment_mgmt import X\n"
        )
        viols, _ = scan(bad)
        if not viols:
            print("[self-test FAIL] violation case produced 0 violations", file=sys.stderr)
            return 1

        # good: compliant modulos/ (imports from cores only)
        good = root / "good"
        (good / "modulos" / "booking").mkdir(parents=True)
        for d in ("modulos", "modulos/booking"):
            (good / d / "__init__.py").write_text("")
        (good / "modulos" / "booking" / "svc.py").write_text(
            "from cores.appointments import Appointment\n"
        )
        viols, _ = scan(good)
        if viols:
            print(f"[self-test FAIL] clean case had violations: {viols}", file=sys.stderr)
            return 1

    print("[self-test OK]")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    root = Path(argv[0]) if argv else Path.cwd()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    violations, had_error = scan(root)
    for v in violations:
        print(v)
    if violations:
        return 1
    return 2 if had_error else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
