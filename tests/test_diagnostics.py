"""Tests for Animated Scenes diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.const import DOMAIN
from custom_components.animated_scenes.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.asyncio
async def test_diagnostics_redacts_entity_ids_and_reports_runtime(
    hass: HomeAssistant,
) -> None:
    """Return redacted config data with a summary of runtime manager state."""
    manager = Animations(hass)
    Animations.instance = manager
    manager.light_owner["light.kitchen"] = object()  # type: ignore[assignment]
    entry = _diagnostic_entry()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["title"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["name"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["lights"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["target"]["entity_id"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["selector"]["animated_scene_switch"] == "**REDACTED**"
    assert diagnostics["runtime"]["active_light_count"] == 1


@pytest.mark.asyncio
async def test_diagnostics_reports_zero_runtime(hass: HomeAssistant) -> None:
    """Return zero runtime counters before the animation manager is initialized."""
    Animations.instance = None

    diagnostics = await async_get_config_entry_diagnostics(hass, _diagnostic_entry())

    assert diagnostics["runtime"] == {
        "active_animation_count": 0,
        "active_light_count": 0,
        "stored_state_count": 0,
    }


def _diagnostic_entry() -> MockConfigEntry:
    """Return a config entry containing every redacted diagnostics key.

    Returns:
        A config entry with top-level and nested entity identifiers plus a
        user-authored scene name.

    """
    return MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Spooky",
        data={
            "name": "Kitchen Spooky",
            "lights": ["light.kitchen"],
            "colors": [],
            "target": {"entity_id": "light.kitchen"},
            "selector": {"animated_scene_switch": "switch.kitchen_spooky"},
        },
        options={},
        source="user",
        unique_id=None,
        entry_id="spooky",
    )
