"""Shared pytest fixtures for Animated Scenes integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import util
from pathlib import Path
import sys
from types import ModuleType

import pytest

import custom_components

pytest_plugins = ("pytest_homeassistant_custom_component",)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Editable installs add a path hook that Home Assistant cannot scan for integrations.
custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
RELEASE_VERSION_SCRIPT_PATH = REPO_ROOT / ".github/scripts/update_release_version.py"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for every test.

    Args:
        enable_custom_integrations: Home Assistant helper fixture.

    Returns:
        None.

    """
    assert enable_custom_integrations is None


def _load_script_module(module_name: str, script_path: Path) -> Iterator[ModuleType]:
    """Load a checked-in script as a temporary importable module.

    Args:
        module_name: Name to use while registering the module in ``sys.modules``.
        script_path: Script path to load.

    Yields:
        ModuleType: The loaded script module.
    """
    spec = util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module


@pytest.fixture
def release_version_script() -> Iterator[ModuleType]:
    """Load the release version script as an importable module.

    Yields:
        ModuleType: The loaded release version script module.

    """
    yield from _load_script_module("update_release_version", RELEASE_VERSION_SCRIPT_PATH)
