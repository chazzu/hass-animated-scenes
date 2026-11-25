"""Shared pytest fixtures for Animated Scenes integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import custom_components

pytest_plugins = ("pytest_homeassistant_custom_component",)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Editable installs add a path hook that Home Assistant cannot scan for integrations.
custom_components.__path__ = [str(REPO_ROOT / "custom_components")]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for every test.

    Args:
        enable_custom_integrations: Home Assistant helper fixture.

    Returns:
        None.

    """
    assert enable_custom_integrations is None
