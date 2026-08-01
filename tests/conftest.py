"""Shared pytest fixtures for Animated Scenes integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.const import DOMAIN

pytest_plugins = ("pytest_homeassistant_custom_component",)

REPO_ROOT = Path(__file__).resolve().parents[1]
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


@pytest.fixture(autouse=True)
def restore_animations_instance() -> Iterator[None]:
    """Restore the global animation singleton after each test.

    Yields:
        None.

    """
    previous_instance = Animations.instance
    try:
        yield
    finally:
        Animations.instance = previous_instance


@pytest.fixture
def integration_domain() -> str:
    """Return the Animated Scenes integration domain.

    Returns:
        str: The integration domain used by Home Assistant tests.

    """
    return DOMAIN


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
