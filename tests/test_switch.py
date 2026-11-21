"""Tests for Animated Scenes switch entities."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
import voluptuous as vol

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
from custom_components.animated_scenes.switch import (
    PLATFORM_SCHEMA,
    AnimatedSceneSwitch,
    async_setup_platform,
)

from .helpers import register_light_services


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

    await async_setup_platform(hass, {CONF_NAME: "Spooky"}, AsyncMock())

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"deprecated_yaml_{DOMAIN}")
    assert issue is not None
    assert issue.issue_domain == DOMAIN


@pytest.mark.parametrize("has_stored_colors", [True, False], ids=["empty", "missing"])
async def test_switch_starts_rgb_ui_colors_without_mutating_config(
    hass: HomeAssistant, has_stored_colors: bool
) -> None:
    """Send converted RGB colors on turn-on while keeping stored config unchanged."""
    manager = _runtime_manager(hass)
    config = _switch_config()
    if not has_stored_colors:
        config.pop(CONF_COLORS)
    source = deepcopy(config)
    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    with patch.object(manager, "start", AsyncMock()) as start:
        await switch.async_turn_on()

    assert start.await_args is not None
    assert start.await_args.args[0][CONF_COLORS] == [
        {
            "color": [255, 0, 0],
            "brightness": 255,
            "weight": 10,
            "color_type": "rgb_color",
        }
    ]
    assert config == source


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


async def test_switch_tracks_animation_events(hass: HomeAssistant) -> None:
    """Reflect only this scene's animation lifecycle in the switch state."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Spooky", data=_switch_config())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for animation, event_state, expected in (
        ("Spooky", EVENT_STATE_STARTED, STATE_ON),
        ("Other", EVENT_STATE_STOPPED, STATE_ON),
        ("Spooky", EVENT_STATE_STOPPED, STATE_OFF),
        ("Other", EVENT_STATE_STARTED, STATE_OFF),
    ):
        hass.bus.async_fire(EVENT_NAME_CHANGE, {"animation": animation, "state": event_state})
        await hass.async_block_till_done()

        state = hass.states.get("switch.animated_scenes_spooky")
        assert state is not None
        assert state.state == expected


async def test_switch_turn_on_stays_off_for_one_shot_scene(hass: HomeAssistant) -> None:
    """Apply the initial update before a one-shot scene releases itself."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "off")
    config = _switch_config()
    config["change_frequency"] = 0
    switch = AnimatedSceneSwitch(hass, config, "entry-id")

    await switch.async_turn_on()
    await hass.async_block_till_done()

    assert [call["entity_id"] for call in calls] == [["light.one"]]
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


@pytest.mark.parametrize(
    ("change_sequence", "weight", "accepted"),
    [(False, 0, False), (True, 0, True), (False, 5, True)],
    ids=["random_zero_rejected", "sequence_zero_accepted", "random_positive_accepted"],
)
def test_platform_schema_checks_color_weights_for_random_mode(
    change_sequence: bool, weight: int, accepted: bool
) -> None:
    """Reject unusable random-mode weights when a legacy YAML scene is validated."""
    config = {
        "platform": DOMAIN,
        "name": "Spooky",
        "lights": ["light.one"],
        "change_sequence": change_sequence,
        "colors": [{"color_type": "rgb_color", "color": [255, 0, 0], "weight": weight}],
    }

    if accepted:
        assert PLATFORM_SCHEMA(config)["change_sequence"] is change_sequence
    else:
        with pytest.raises(vol.Invalid, match="colors_malformed"):
            PLATFORM_SCHEMA(config)


async def test_switch_syncs_with_scene_started_before_entry_setup(hass: HomeAssistant) -> None:
    """Show a service-started scene as on and keep turn-on from restarting it."""
    assert await async_setup_component(hass, DOMAIN, {})
    manager = Animations.instance
    assert manager is not None
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    data = _switch_config()
    await manager.start(
        {
            "name": "Spooky",
            "lights": ["light.one"],
            CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
            "change_frequency": 3600,
        }
    )
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    calls.clear()

    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Spooky", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.animated_scenes_spooky")
    assert state is not None
    assert state.state == STATE_ON
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )
    await hass.async_block_till_done()
    assert calls == []
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("existing", "yaml_name", "imported"),
    [
        ({"title": "Renamed", "unique_id": "Spooky", "name": "Renamed"}, "Spooky", False),
        ({"title": "Spooky", "unique_id": None, "name": "Renamed"}, "Spooky", False),
        ({"title": "Other", "unique_id": None, "name": "Spooky"}, "Spooky", False),
        ({"title": "Renamed", "unique_id": "Spooky", "name": "Renamed"}, "Fresh", True),
    ],
    ids=["renamed_import", "legacy_renamed_import", "same_scene_name", "new_scene"],
)
async def test_yaml_setup_imports_only_scenes_without_entries(
    hass: HomeAssistant,
    existing: dict[str, str | None],
    yaml_name: str,
    imported: bool,
) -> None:
    """Skip a YAML scene that already has an entry, even after a UI rename."""
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=existing["title"],
        unique_id=existing["unique_id"],
        source=SOURCE_IMPORT,
        data={CONF_NAME: existing["name"], "entity_type": "scene"},
    ).add_to_hass(hass)
    config = PLATFORM_SCHEMA(
        {
            "platform": DOMAIN,
            "name": yaml_name,
            "lights": ["light.one"],
            "colors": [{"color_type": "rgb_color", "color": [255, 0, 0]}],
        }
    )

    flow_manager = hass.config_entries.flow
    with (
        patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)),
        patch.object(flow_manager, "async_init", wraps=flow_manager.async_init) as start_import,
    ):
        await async_setup_platform(hass, config, AsyncMock())
        await hass.async_block_till_done()

    # A skipped scene must not even start an import flow, which would log a
    # "Not importing" warning on every restart before aborting.
    assert start_import.call_count == (1 if imported else 0)
    names = sorted(entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN))
    assert names == sorted([str(existing["name"]), *([yaml_name] if imported else [])])
    assert hass.config_entries.flow.async_progress() == []


async def test_switch_turn_off_stops_running_scene(hass: HomeAssistant) -> None:
    """Stop the scene's animation and show the switch off after turn-off."""
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    data = _switch_config()
    data["change_frequency"] = 3600
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Spooky", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = Animations.instance
    assert manager is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )
    await hass.async_block_till_done()
    on_state = hass.states.get("switch.animated_scenes_spooky")
    calls.clear()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )
    await hass.async_block_till_done()

    assert on_state is not None
    assert on_state.state == STATE_ON
    off_state = hass.states.get("switch.animated_scenes_spooky")
    assert off_state is not None
    assert off_state.state == STATE_OFF
    assert manager.animations == {}
    assert [call["rgb_color"] for call in calls] == [(1, 2, 3)]


async def test_switch_state_is_not_polled(hass: HomeAssistant) -> None:
    """Rely on animation events for state instead of a periodic poll."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Spooky", data=_switch_config())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(AnimatedSceneSwitch, "async_update_ha_state", AsyncMock()) as update:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
        await hass.async_block_till_done()

    update.assert_not_awaited()
