"""Tests for Animated Scenes switch entities."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.const import (
    COLOR_SELECTOR_RGB_UI,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_COLORS,
    DOMAIN,
    EVENT_NAME_CHANGE,
    EVENT_STATE_STARTED,
    EVENT_STATE_STOPPED,
    INTEGRATION_NAME,
)
from custom_components.animated_scenes.switch import AnimatedSceneSwitch, async_setup_platform


def _switch_config() -> dict[str, object]:
    """Return a valid scene switch config-entry payload.

    Returns:
        A config-entry data dictionary that exercises RGB UI color conversion
        and contains the runtime keys required to start an animation.

    """
    return {
        "name": "Spooky",
        "icon": "mdi:lightbulb",
        "lights": ["light.one"],
        "colors": {},
        CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_RGB_UI,
        CONF_COLOR_RGB_DICT: {"one": {"color": [255, 0, 0], "brightness": 255, "weight": 10}},
        "ignore_off": True,
        "restore": True,
        "restore_power": False,
        "brightness": 255,
        "transition": 1,
        "change_frequency": 1,
        "change_amount": "all",
        "change_sequence": False,
        "animate_brightness": True,
        "animate_color": True,
        "priority": 0,
        "entity_type": "scene",
    }


def _runtime_manager(hass: HomeAssistant) -> Animations:
    """Return a runtime manager registered as the active singleton."""
    manager = Animations(hass)
    Animations.instance = manager
    return manager


@pytest.mark.asyncio
async def test_legacy_yaml_repair_uses_integration_domain(hass: HomeAssistant) -> None:
    """Register legacy YAML repairs under the Animated Scenes integration."""
    MockConfigEntry(domain=DOMAIN, title="Spooky", data={}, entry_id="spooky").add_to_hass(hass)

    with patch("custom_components.animated_scenes.switch.async_create_issue") as create_issue:
        await async_setup_platform(hass, {CONF_NAME: "Spooky"}, AsyncMock())

    create_issue.assert_called_once()
    assert create_issue.call_args.args[:3] == (
        hass,
        DOMAIN,
        f"deprecated_yaml_{DOMAIN}",
    )
    assert create_issue.call_args.kwargs["issue_domain"] == DOMAIN


@pytest.mark.asyncio
async def test_switch_animation_config_ready_in_constructor(hass: HomeAssistant) -> None:
    """Build runtime animation data before the switch can be turned on.

    The constructor must prepare the RGB UI color list synchronously so an
    immediate service or UI turn-on cannot start an animation with an empty
    config.
    """
    switch = AnimatedSceneSwitch(hass, _switch_config(), "entry-id")

    assert switch._animation_config["colors"] == [
        {
            "color": [255, 0, 0],
            "brightness": 255,
            "weight": 10,
            "color_type": "rgb_color",
        }
    ]


@pytest.mark.asyncio
async def test_switch_animation_config_does_not_mutate_source_config(
    hass: HomeAssistant,
) -> None:
    """Keep RGB UI conversion isolated to the runtime animation copy."""
    config = _switch_config()
    config.pop(CONF_COLORS)

    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    assert CONF_COLORS not in config
    assert switch._animation_config[CONF_COLORS] == [
        {
            "color": [255, 0, 0],
            "brightness": 255,
            "weight": 10,
            "color_type": "rgb_color",
        }
    ]


def test_switch_extra_state_attributes_use_runtime_config(hass: HomeAssistant) -> None:
    """Expose normalized runtime values in switch state attributes."""
    config = _switch_config()
    config[CONF_COLORS] = [{"stale": True}]

    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    assert switch.extra_state_attributes is not None
    assert switch.extra_state_attributes[CONF_COLORS] == [
        {
            "color": [255, 0, 0],
            "brightness": 255,
            "weight": 10,
            "color_type": "rgb_color",
        }
    ]


def test_switch_exposes_animated_scenes_device_info(hass: HomeAssistant) -> None:
    """Group switch entities under the Animated Scenes device."""
    switch = AnimatedSceneSwitch(hass, _switch_config(), "entry-id")

    assert switch.device_info == {
        "identifiers": {(DOMAIN, "animated_scenes")},
        "name": INTEGRATION_NAME,
        "manufacturer": INTEGRATION_NAME,
    }


@pytest.mark.asyncio
async def test_switch_tracks_animation_events(hass: HomeAssistant) -> None:
    """Update switch state immediately when animation lifecycle events fire."""
    switch = AnimatedSceneSwitch(hass, _switch_config(), "entry-id")
    switch.hass = hass
    with patch.object(AnimatedSceneSwitch, "async_write_ha_state") as write_state:
        await switch.async_added_to_hass()

        hass.bus.async_fire(
            EVENT_NAME_CHANGE,
            {"animation": "Spooky", "state": EVENT_STATE_STARTED},
        )
        await hass.async_block_till_done()

        assert switch.is_on is True
        write_state.assert_called()
        started_write_count = write_state.call_count

        hass.bus.async_fire(
            EVENT_NAME_CHANGE,
            {"animation": "Spooky", "state": EVENT_STATE_STOPPED},
        )
        await hass.async_block_till_done()

        assert switch.is_on is False
        assert write_state.call_count == started_write_count + 1

        hass.bus.async_fire(
            EVENT_NAME_CHANGE,
            {"animation": "Other", "state": EVENT_STATE_STARTED},
        )
        await hass.async_block_till_done()

        assert switch.is_on is False
        assert write_state.call_count == started_write_count + 1


@pytest.mark.asyncio
async def test_switch_turn_on_stays_off_for_one_shot_scene(hass: HomeAssistant) -> None:
    """Apply one initial update before a one-shot scene releases itself."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "off")
    config = _switch_config()
    config["change_frequency"] = 0
    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()) as safe_call:
        await switch.async_turn_on()

    assert any(call.args[3]["entity_id"] == "light.one" for call in safe_call.await_args_list)
    assert switch.is_on is False
    assert manager.animations == {}


@pytest.mark.asyncio
async def test_switch_rejects_empty_rgb_ui_colors_before_animation_loop(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject empty RGB UI color storage before random color selection runs."""
    manager = _runtime_manager(hass)
    config = _switch_config()
    config[CONF_COLOR_RGB_DICT] = {}
    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    with caplog.at_level(logging.ERROR):
        await switch.async_turn_on()

    assert switch.is_on is False
    assert manager.animations == {}
    assert "Failed to start animated scene Spooky" in caplog.text


@pytest.mark.asyncio
async def test_switch_stays_off_when_one_shot_animation_releases(
    hass: HomeAssistant,
) -> None:
    """Keep the switch off when start completes without a running animation."""
    manager = _runtime_manager(hass)
    switch = AnimatedSceneSwitch(hass, _switch_config(), "entry-id")
    switch.hass = hass

    with patch.object(manager, "start", AsyncMock()) as start:
        await switch.async_turn_on()

    start.assert_awaited_once()
    assert switch.is_on is False
