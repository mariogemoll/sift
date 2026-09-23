#!/usr/bin/env python
"""Enforce the package layering over the AST.

Three tiers. `core` is pure domain and imports nothing else in the package. Each
branch owns one heavy dependency and may not import a sibling branch. The
convergence tier may import anything below it. `settings` is a root module
anything may import.

A module reaching sideways for a fact is telling you that fact belongs in
`core`; a module needing two capabilities belongs in the convergence tier by
construction.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "sift"
SRC = Path(__file__).resolve().parent.parent / "src"

CORE = "core"
BRANCHES = frozenset({"judge", "storage", "ingest"})
CONVERGENCE = frozenset({"pipeline", "api", "cli", "mcp"})
ROOT_MODULES = frozenset({"settings"})


def allowed_imports(subpackage: str | None) -> frozenset[str]:
    """Which subpackages a module in `subpackage` may import from."""
    if subpackage in CONVERGENCE:
        return frozenset({CORE}) | BRANCHES | CONVERGENCE
    if subpackage in BRANCHES:
        return frozenset({CORE})
    # core, and the root modules, import nothing else in the package
    return frozenset()


def subpackage_of(module: str) -> str | None:
    """`sift.api.routes.health` -> `api`; `sift.settings` and `sift` -> None."""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != PACKAGE or parts[1] in ROOT_MODULES:
        return None
    return parts[1]


def module_name(path: Path) -> str:
    relative = path.relative_to(SRC).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(parts)


def imported_modules(tree: ast.AST, module: str) -> list[tuple[str, int]]:
    """Every in-package module this file imports, with the line it happens on."""
    package = module.rsplit(".", 1)[0] if "." in module else module
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.split(".")[0] == PACKAGE
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            if target.split(".")[0] == PACKAGE:
                found.append((target, node.lineno))
    return found


def violations(path: Path) -> list[str]:
    module = module_name(path)
    source_subpackage = subpackage_of(module)
    permitted = allowed_imports(source_subpackage)
    problems: list[str] = []

    for target, line in imported_modules(ast.parse(path.read_text()), module):
        target_parts = target.split(".")
        if len(target_parts) < 2:
            continue
        target_subpackage = target_parts[1]
        if target_subpackage in ROOT_MODULES:
            continue
        if target_subpackage == source_subpackage:
            continue
        if target_subpackage not in permitted:
            where = source_subpackage or "the package root"
            problems.append(
                f"{path.relative_to(SRC.parent)}:{line}: {where} may not import "
                f"{target_subpackage} ({target})"
            )
    return problems


def main() -> int:
    problems = [
        problem for path in sorted((SRC / PACKAGE).rglob("*.py")) for problem in violations(path)
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} layering violation(s)", file=sys.stderr)
        return 1
    print("layering ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
