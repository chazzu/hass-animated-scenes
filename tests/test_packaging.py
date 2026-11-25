"""Tests for Python package metadata."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
CONST_PATH = REPO_ROOT / "custom_components" / "animated_scenes" / "const.py"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _const_version() -> str:
    """Read VERSION from const.py without importing the integration package."""
    module = ast.parse(CONST_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError("VERSION constant not found")


def test_project_version_is_dynamic_from_integration_constant() -> None:
    """Keep package metadata version derived from const.py without importing HA."""
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert "version" in pyproject["project"].get("dynamic", [])
    assert "version" not in pyproject["project"]
    assert (
        pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        == "custom_components.animated_scenes.const.VERSION"
    )
    assert _const_version()


def test_package_data_includes_runtime_yaml_and_brand_assets() -> None:
    """Include Home Assistant service descriptions and brand icons in packages."""
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "*.yaml" in package_data["custom_components.animated_scenes"]
    assert "brand/*.png" in package_data["custom_components.animated_scenes"]
