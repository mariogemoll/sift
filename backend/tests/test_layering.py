"""The layering rule is load-bearing, so the checker that enforces it is tested."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_layering import (  # noqa: E402
    allowed_imports,
    imported_modules,
    subpackage_of,
)


def test_core_may_import_nothing_in_the_package() -> None:
    assert allowed_imports("core") == frozenset()


def test_branches_may_import_core_but_never_a_sibling() -> None:
    permitted = allowed_imports("storage")
    assert "core" in permitted
    assert "judge" not in permitted
    assert "ingest" not in permitted


def test_convergence_may_import_anything_below() -> None:
    permitted = allowed_imports("api")
    assert {"core", "storage", "judge", "ingest"} <= permitted


def test_subpackage_of() -> None:
    assert subpackage_of("sift.api.routes.health") == "api"
    assert subpackage_of("sift.core") == "core"
    assert subpackage_of("sift.settings") is None
    assert subpackage_of("sift") is None


def test_relative_imports_resolve_to_absolute_modules() -> None:
    source = "from ..judge import ask\nfrom .models import Base\n"
    found = imported_modules(ast.parse(source), "sift.storage.papers")
    assert {module for module, _ in found} == {"sift.judge", "sift.storage.models"}


def test_third_party_imports_are_ignored() -> None:
    source = "import sqlalchemy\nfrom fastapi import APIRouter\n"
    assert imported_modules(ast.parse(source), "sift.api.app") == []
