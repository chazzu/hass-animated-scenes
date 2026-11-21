"""Tests for Animated Scenes runtime manager and service setup."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import colorsys
import contextlib
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry, DiscoveryKey
from homeassistant.const import CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_rgbw_to_rgb,
    color_rgbww_to_rgb,
    color_temperature_to_rgb,
    color_xy_to_RGB,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes import async_migrate_entry, async_setup, async_unload_entry
from custom_components.animated_scenes.animations import (
    Animation,
    Animations,
    _rgb_to_kelvin,
    safe_call,
)
from custom_components.animated_scenes.const import (
    COLOR_SELECTOR_YAML,
    CONF_ANIMATED_SCENE_SWITCH,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_ENTITY_TYPE,
    CONF_LIGHTS,
    CONF_SKIP_RESTORE,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    ENTITY_SCENE,
    EVENT_NAME_CHANGE,
    EVENT_STATE_UPDATED,
    MAX_KELVIN,
    MIN_KELVIN,
    PRIORITY_MIN,
)

from .helpers import animation_tasks, register_light_services

DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})
LIGHT_ON: dict[str, object] = {"color_mode": "rgb", "brightness": 100, "rgb_color": (1, 2, 3)}


def _animation_config(name: str, lights: list[str], priority: int = 0) -> dict[str, object]:
    """Return a minimal validated runtime animation configuration.

    Args:
        name: Unique animation name used by the manager.
        lights: Light entity ids controlled by the animation.
        priority: Ownership priority used when animations overlap.

    Returns:
        A service-schema-compatible configuration dictionary for constructing
        an ``Animation`` directly in manager unit tests.

    """
    return {
        "name": name,
        "lights": lights,
        "colors": [{"color_type": "rgb_color", "color": (255, 0, 0)}],
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
        "priority": priority,
    }


def _scene_entry() -> ConfigEntry:
    """Return a scene config entry for unload lifecycle tests.

    Returns:
        A Home Assistant ``ConfigEntry`` carrying the minimal Animated Scenes
        scene data needed by ``async_unload_entry``.

    """
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Spooky",
        data={CONF_ENTITY_TYPE: ENTITY_SCENE, "name": "Spooky"},
        discovery_keys=DISCOVERY_KEYS,
        options={},
        source="user",
        subentries_data={},
        unique_id=None,
        entry_id="entry-spooky",
    )


def _runtime_manager(hass: HomeAssistant) -> Animations:
    """Return a runtime manager registered as the active singleton."""
    manager = Animations(hass)
    Animations.instance = manager
    return manager


async def _start(
    manager: Animations, name: str, lights: list[str], **overrides: object
) -> Animation:
    """Start a scene whose loop stays idle and return its running animation.

    Args:
        manager: Runtime manager that starts the scene.
        name: Scene name.
        lights: Lights controlled by the scene.
        **overrides: Scene configuration values to override.

    Returns:
        The animation registered by the public manager start path.

    """
    await manager.start({**_animation_config(name, lights), "change_frequency": 3600, **overrides})
    await asyncio.sleep(0)
    return manager.animations[name]


def _repeating_config(name: str, lights: list[str]) -> dict[str, Any]:
    """Return a scene configuration whose loop stays idle during a test."""
    return {**_animation_config(name, lights), "change_frequency": 3600}


def _full_scene_data(name: str = "Spooky") -> dict[str, object]:
    """Return stored data for a real scene config entry."""
    return {
        **_animation_config(name, ["light.one"]),
        "colors": [{"color_type": "rgb_color", "color": [255, 0, 0]}],
        "change_frequency": 3600,
        "icon": "mdi:lightbulb",
        CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_YAML,
        CONF_COLOR_RGB_DICT: {},
    }


async def _setup_scene_entry(hass: HomeAssistant, data: dict[str, object]) -> MockConfigEntry:
    """Set up a real scene config entry and return it."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, title=str(data[CONF_NAME]), data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize("kelvin", [2200, 4000, 6200])
def test_kelvin_rgb_round_trip_stays_near_source(kelvin: int) -> None:
    """Keep warm, neutral, and cool conversions near their source temperature."""
    red, green, blue = color_temperature_to_rgb(kelvin)

    inferred = _rgb_to_kelvin((round(red), round(green), round(blue)))

    # Integer RGB channels lose temperature precision at the cool end.
    assert abs(inferred - kelvin) <= 500


def test_repeating_animation_frequency_is_never_zero(hass: HomeAssistant) -> None:
    """Keep every accepted repeating frequency above zero at runtime."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on")

    for change_frequency in (0.1, [0.1, 0.2]):
        config = _animation_config("Repeating", ["light.one"])
        config["change_frequency"] = change_frequency
        animation = Animation(hass, manager.validate_start(config))

        assert all(animation.get_change_frequency() >= 0.1 for _ in range(20))


@pytest.mark.parametrize("register_service", [False, True], ids=["missing", "invalid_payload"])
async def test_safe_call_suppresses_service_failures(
    hass: HomeAssistant, register_service: bool
) -> None:
    """Keep animation ticks alive when Home Assistant rejects a light call."""
    calls = register_light_services(hass) if register_service else []

    await safe_call(hass, "light", "turn_on", {"entity_id": "light.one", "invalid": True})
    await hass.async_block_till_done()

    assert calls == []


async def test_safe_call_propagates_unexpected_runtime_errors() -> None:
    """Expose non-Home Assistant errors instead of masking implementation bugs."""
    fake_hass = cast(
        "HomeAssistant",
        SimpleNamespace(
            services=SimpleNamespace(async_call=AsyncMock(side_effect=RuntimeError("bug")))
        ),
    )

    with pytest.raises(RuntimeError, match="bug"):
        await safe_call(fake_hass, "light", "turn_on", {"entity_id": "light.one"})


async def test_add_lights_updates_running_animation(hass: HomeAssistant) -> None:
    """Track added lights once and notify event-driven entities."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"])
    events: list[Mapping[str, Any]] = []
    hass.bus.async_listen(EVENT_NAME_CHANGE, lambda event: events.append(event.data))

    for _ in range(2):
        await manager.add_lights_to_animation({CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]})
    await hass.async_block_till_done()

    assert animation.lights.count("light.two") == 1
    assert manager.light_owner["light.two"] is animation
    assert {"animation": "Spooky", "state": EVENT_STATE_UPDATED} in events

    await manager.stop({CONF_NAME: "Spooky"})
    assert manager.light_owner == {}


@pytest.mark.parametrize(
    ("registry_args", "message"),
    [
        (None, "was not found"),
        (("switch", "unrelated_integration", "unrelated-switch"), "does not belong"),
    ],
    ids=["missing", "unrelated"],
)
async def test_add_lights_to_animation_rejects_invalid_switch(
    hass: HomeAssistant, registry_args: tuple[str, str, str] | None, message: str
) -> None:
    """Raise a clean integration error for switches outside this integration."""
    manager = _runtime_manager(hass)
    entity_id = "switch.missing"
    if registry_args is not None:
        entity_id = er.async_get(hass).async_get_or_create(*registry_args).entity_id

    with pytest.raises(IntegrationError, match=message):
        await manager.add_lights_to_animation(
            {CONF_ANIMATED_SCENE_SWITCH: entity_id, CONF_LIGHTS: ["light.two"]}
        )


async def test_add_lights_to_animation_resolves_renamed_switch_by_config_entry(
    hass: HomeAssistant,
) -> None:
    """Resolve a scene through stable registry identity after a display-name change."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENTITY_TYPE: ENTITY_SCENE, CONF_NAME: "Spooky"},
        entry_id="scene-spooky",
    )
    entry.add_to_hass(hass)
    registry_entry = er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        entry.entry_id,
        config_entry=entry,
        suggested_object_id="renamed_spooky",
    )

    await manager.add_lights_to_animation(
        {
            CONF_ANIMATED_SCENE_SWITCH: registry_entry.entity_id,
            CONF_LIGHTS: ["light.two"],
        }
    )

    assert "light.two" in animation.lights
    await manager.stop({CONF_NAME: "Spooky"})


async def test_add_lights_tracks_only_lights_that_become_active(hass: HomeAssistant) -> None:
    """Exclude missing and ignored-off additions from light ownership."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    hass.states.async_set("light.off", "off")
    animation = await _start(manager, "Spooky", ["light.one"], ignore_off=False)
    new_lights = {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.missing", "light.off"]}

    await manager.add_lights_to_animation(new_lights)

    assert set(manager.light_owner) == {"light.one"}

    hass.states.async_set("light.off", "on")
    await manager.add_lights_to_animation(new_lights)

    assert manager.light_owner["light.off"] is animation
    assert "light.missing" not in manager.light_owner
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("skip_restore", "expected_colors"),
    [(True, []), (False, [(1, 2, 3)])],
    ids=["skip_restore", "restore"],
)
async def test_remove_final_light_honors_restore_and_stops_animation(
    hass: HomeAssistant, skip_restore: bool, expected_colors: list[tuple[int, int, int]]
) -> None:
    """Restore as requested, notify listeners, and stop an emptied animation."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"])
    await hass.async_block_till_done()
    calls.clear()
    events: list[Mapping[str, Any]] = []
    hass.bus.async_listen(EVENT_NAME_CHANGE, lambda event: events.append(event.data))

    await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: skip_restore})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == expected_colors
    assert "light.one" not in animation.lights
    assert manager.animations == {}
    assert manager.light_owner == {}
    assert {"animation": "Spooky", "state": EVENT_STATE_UPDATED} in events


async def test_remove_lights_removes_overlapping_light_from_every_animation(
    hass: HomeAssistant,
) -> None:
    """Remove an overlapping light from all priorities and future updates."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    for light in ("light.one", "light.low", "light.high"):
        hass.states.async_set(light, "on", LIGHT_ON)
    low = await _start(manager, "Low", ["light.one", "light.low"], priority=1)
    high = await _start(manager, "High", ["light.one", "light.high"], priority=10)

    await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})
    await hass.async_block_till_done()
    calls.clear()
    await asyncio.gather(low.update_lights(), high.update_lights())
    await hass.async_block_till_done()

    assert "light.one" not in low.lights
    assert "light.one" not in high.lights
    assert "light.one" not in manager.light_owner
    assert calls
    assert all(call["entity_id"] != ["light.one"] for call in calls)
    await manager.stop({CONF_NAME: "Low"})
    await manager.stop({CONF_NAME: "High"})


async def test_removed_light_is_not_reanimated_by_its_restore(hass: HomeAssistant) -> None:
    """Ignore the off-to-on event produced by restoring a removed light."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"])
    hass.states.async_set("light.one", "off", LIGHT_ON)
    await hass.async_block_till_done()
    calls.clear()

    await manager.remove_lights({CONF_LIGHTS: ["light.one"]})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(1, 2, 3)]
    assert animation.get_active_lights() == []
    assert manager.states == {}
    assert manager.light_owner == {}


async def test_cancelled_remove_lights_still_releases_light(hass: HomeAssistant) -> None:
    """Finish releasing a removed light even when the service caller is cancelled."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    await _start(manager, "High", ["light.one", "light.two"], priority=10)
    await hass.async_block_till_done()
    calls.clear()

    removal = asyncio.ensure_future(
        manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: False})
    )
    # Cancel after the first step, where the release used to wait in a gather.
    await asyncio.sleep(0)
    removal.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await removal
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(1, 2, 3)]
    assert "light.one" not in manager.light_owner
    assert set(manager.states) == {"light.two"}
    low = await _start(manager, "Low", ["light.one"], priority=1)
    assert manager.light_owner["light.one"] is low
    await manager.stop({CONF_NAME: "High"})
    await manager.stop({CONF_NAME: "Low"})
    assert manager.states == {}
    assert manager.light_owner == {}


async def test_start_clamps_oversized_change_amount(hass: HomeAssistant) -> None:
    """Normalize service change_amount before the animation loop can sample lights."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    animation = await _start(manager, "Spooky", ["light.one"], change_amount=2)

    assert animation.get_change_amount() == 1
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("restore", "expected_colors"),
    [(True, [(255, 0, 0), (1, 2, 3)]), (False, [(255, 0, 0)])],
    ids=["restore", "no_restore"],
)
async def test_one_shot_release_honors_restore_setting(
    hass: HomeAssistant, restore: bool, expected_colors: list[tuple[int, int, int]]
) -> None:
    """Apply one update and restore only when configured to do so."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    await manager.start(
        {**_animation_config("One Shot", ["light.one"]), "change_frequency": 0, "restore": restore}
    )
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == expected_colors
    assert manager.animations == {}


async def test_start_tracks_only_active_lights_across_restart(hass: HomeAssistant) -> None:
    """Avoid ownership for missing and ignored-off configured lights."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.active", "on", LIGHT_ON)
    hass.states.async_set("light.off", "off")
    lights = ["light.active", "light.off", "light.missing"]

    await _start(manager, "Spooky", list(lights), ignore_off=False)
    assert set(manager.light_owner) == {"light.active"}

    await manager.stop({CONF_NAME: "Spooky"})
    hass.states.async_set("light.off", "on", LIGHT_ON)
    await _start(manager, "Spooky", list(lights), ignore_off=False)

    assert set(manager.light_owner) == {"light.active", "light.off"}
    await manager.stop({CONF_NAME: "Spooky"})


async def test_startup_failure_rolls_back_runtime_state(hass: HomeAssistant) -> None:
    """Stop tracking a light when initial startup fails."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    with (
        patch.object(Animation, "start", AsyncMock(side_effect=RuntimeError("startup failed"))),
        pytest.raises(RuntimeError, match="startup failed"),
    ):
        await manager.start(_animation_config("Spooky", ["light.one"]))
    await hass.async_block_till_done()
    calls.clear()

    hass.states.async_set("light.one", "off", LIGHT_ON)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await hass.async_block_till_done()

    assert manager.animations == {}
    assert manager.light_owner == {}
    assert manager.states == {}
    assert calls == []


async def test_update_skips_light_removed_after_tick_selection(hass: HomeAssistant) -> None:
    """Tolerate ownership removal after a tick selects its lights."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one", "light.two"])
    await hass.async_block_till_done()
    calls.clear()
    selected_update_started = asyncio.Event()
    continue_selected_update = asyncio.Event()
    original_update_light = animation.update_light

    async def pause_removed_light(entity_id: str, initial: bool = False) -> None:
        """Pause the selected light until its ownership has been removed."""
        if entity_id == "light.one":
            selected_update_started.set()
            await continue_selected_update.wait()
        await original_update_light(entity_id, initial)

    with patch.object(animation, "update_light", side_effect=pause_removed_light):
        update_task = asyncio.create_task(animation.update_lights())
        await selected_update_started.wait()
        await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})
        continue_selected_update.set()
        await update_task
    await hass.async_block_till_done()

    assert manager.animations["Spooky"] is animation
    assert animation.get_active_lights() == ["light.two"]
    assert all(call["entity_id"] != ["light.one"] for call in calls)
    await manager.stop({CONF_NAME: "Spooky"})


async def test_concurrent_same_name_start_replaces_only_after_startup(
    hass: HomeAssistant,
) -> None:
    """Serialize same-name starts and keep stale cleanup from removing the replacement."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    initial_update_started = asyncio.Event()
    continue_initial_update = asyncio.Event()
    call_count = 0

    async def pause_first_update(*_: object) -> None:
        """Pause only the first light service call across both starts."""
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            initial_update_started.set()
            await continue_initial_update.wait()

    with patch("custom_components.animated_scenes.animations.safe_call", pause_first_update):
        first_start = asyncio.create_task(manager.start(_animation_config("Spooky", ["light.one"])))
        await initial_update_started.wait()
        original = manager.animations["Spooky"]
        second_start = asyncio.create_task(
            manager.start(_animation_config("Spooky", ["light.one"]))
        )
        await asyncio.sleep(0)

        assert not second_start.done()

        continue_initial_update.set()
        await asyncio.gather(first_start, second_start)
        replacement = manager.animations["Spooky"]

        assert replacement is not original
        assert len(animation_tasks("Spooky")) == 1

        await original.release()

        assert manager.animations["Spooky"] is replacement
        await manager.stop({CONF_NAME: "Spooky"})


async def test_remove_final_light_waits_for_startup_and_leaves_no_empty_task(
    hass: HomeAssistant,
) -> None:
    """Serialize final-light removal until startup can create and stop its task."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    initial_update_started = asyncio.Event()
    continue_initial_update = asyncio.Event()

    async def pause_initial_update(*_: object) -> None:
        """Pause the startup light service call until removal is waiting."""
        initial_update_started.set()
        await continue_initial_update.wait()

    with patch("custom_components.animated_scenes.animations.safe_call", pause_initial_update):
        start_task = asyncio.create_task(manager.start(_animation_config("Spooky", ["light.one"])))
        await initial_update_started.wait()
        animation = manager.animations["Spooky"]
        remove_task = asyncio.create_task(
            manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})
        )
        await asyncio.sleep(0)

        assert not remove_task.done()

        continue_initial_update.set()
        await asyncio.gather(start_task, remove_task)

    assert animation.get_active_lights() == []
    assert animation_tasks("Spooky") == []
    assert manager.animations == {}


async def test_update_lights_clamps_change_amount_to_active_lights(
    hass: HomeAssistant,
) -> None:
    """Clamp runtime sampling after the active light set changes."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one", "light.two"], change_amount=2)
    await manager.remove_lights({CONF_LIGHTS: ["light.two"], CONF_SKIP_RESTORE: True})
    await hass.async_block_till_done()
    calls.clear()

    await animation.update_lights()
    await hass.async_block_till_done()

    assert [call["entity_id"] for call in calls] == [["light.one"]]
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize("change_amount", ["3", "[1, 3]"])
async def test_start_service_accepts_text_change_amount(
    hass: HomeAssistant,
    change_amount: str,
) -> None:
    """Accept change_amount values submitted by the text service selector."""
    await async_setup(hass, {})
    assert Animations.instance is not None
    manager = Animations.instance
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            **_animation_config("Spooky", ["light.one"]),
            "change_amount": change_amount,
        },
        blocking=True,
    )

    assert manager.animations["Spooky"].get_change_amount() == 1
    await manager.stop({"name": "Spooky"})


@pytest.mark.parametrize(
    "invalid_data",
    [
        {CONF_LIGHTS: None},
        {"priority": "high"},
    ],
)
def test_validate_start_converts_normalization_errors_to_integration_error(
    hass: HomeAssistant, invalid_data: dict[str, object]
) -> None:
    """Report malformed service data with IntegrationError instead of raw exceptions."""
    manager = _runtime_manager(hass)
    data = _animation_config("Spooky", ["light.one"])
    data.update(invalid_data)

    with pytest.raises(IntegrationError, match="Service data did not match schema"):
        manager.validate_start(data)


async def test_stop_by_name_ends_task_and_clears_runtime(hass: HomeAssistant) -> None:
    """Stop the loop and release a named animation without service validation."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _start(manager, "Spooky", ["light.one"])
    assert len(animation_tasks("Spooky")) == 1

    await manager.stop_by_name("Spooky")

    assert animation_tasks("Spooky") == []
    assert manager.animations == {}
    assert manager.states == {}
    assert manager.light_owner == {}


async def test_unload_stops_running_scene_and_keeps_services(hass: HomeAssistant) -> None:
    """Stop a scene on real entry unload while keeping public services available."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    entry = await _setup_scene_entry(hass, _full_scene_data())
    manager = Animations.instance
    assert manager is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )
    await asyncio.sleep(0)
    assert len(animation_tasks("Spooky")) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert animation_tasks("Spooky") == []
    assert manager.animations == {}
    assert Animations.instance is manager

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {**_animation_config("Manual", ["light.one"]), "change_frequency": 3600},
        blocking=True,
    )
    assert "Manual" in manager.animations
    await manager.stop({CONF_NAME: "Manual"})


@pytest.mark.parametrize(
    ("data", "expected_type"),
    [
        ({CONF_NAME: "Legacy"}, ENTITY_SCENE),
        (
            {CONF_NAME: "Activity Sensor", CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR},
            ENTITY_ACTIVITY_SENSOR,
        ),
    ],
)
async def test_migrate_entry_persists_entity_type(
    hass: HomeAssistant, data: dict[str, str], expected_type: str
) -> None:
    """Default legacy scenes while preserving explicit activity sensors."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=1)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.version == 2
    assert entry.data[CONF_ENTITY_TYPE] == expected_type


async def test_legacy_scene_migrates_runs_and_unloads(hass: HomeAssistant) -> None:
    """Run a legacy scene without a persisted entity type through its switch."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    entry = await _setup_scene_entry(hass, _full_scene_data("Legacy"))
    manager = Animations.instance
    assert manager is not None

    assert entry.version == 2
    assert entry.data[CONF_ENTITY_TYPE] == ENTITY_SCENE
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_legacy"}, blocking=True
    )
    assert "Legacy" in manager.animations

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert manager.animations == {}


async def test_stored_zero_start_frequency_range_still_runs(hass: HomeAssistant) -> None:
    """Keep an upgraded scene with a zero-start range running from its switch."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _setup_scene_entry(hass, {**_full_scene_data(), "change_frequency": [0, 5]})
    manager = Animations.instance
    assert manager is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )

    animation = manager.animations["Spooky"]
    assert all(0.1 <= animation.get_change_frequency() <= 5 for _ in range(50))
    await manager.stop({CONF_NAME: "Spooky"})


async def test_unload_keeps_animation_when_platform_unload_fails(
    hass: HomeAssistant,
) -> None:
    """Keep the scene running when Home Assistant cannot unload its platform."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _start(manager, "Spooky", ["light.one"])
    entry = _scene_entry()

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert await async_unload_entry(hass, entry) is False

    assert len(animation_tasks("Spooky")) == 1
    assert "Spooky" in manager.animations
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (
            {"color_mode": "color_temp", "brightness": 100, "color_temp_kelvin": 2700},
            {"brightness": 100, "color_temp_kelvin": 2700},
        ),
        ({"color_mode": "onoff"}, {}),
        ({"color_mode": "white", "brightness": 100}, {"white": 100}),
        (
            {"color_mode": "hs", "brightness": 100, "hs_color": (10.0, 20.0)},
            {"brightness": 100, "hs_color": (10.0, 20.0)},
        ),
        (
            {"color_mode": "xy", "brightness": 100, "xy_color": (0.3, 0.4)},
            {"brightness": 100, "xy_color": (0.3, 0.4)},
        ),
        (
            {"color_mode": "rgbw", "brightness": 100, "rgbw_color": (1, 2, 3, 4)},
            {"brightness": 100, "rgbw_color": (1, 2, 3, 4)},
        ),
        (
            {"color_mode": "rgbww", "brightness": 100, "rgbww_color": (1, 2, 3, 4, 5)},
            {"brightness": 100, "rgbww_color": (1, 2, 3, 4, 5)},
        ),
        (
            {"brightness": 100, "rgb_color": (1, 2, 3)},
            {"brightness": 100, "rgb_color": (1, 2, 3)},
        ),
    ],
    ids=["color_temp", "onoff", "white", "hs", "xy", "rgbw", "rgbww", "no_color_mode"],
)
async def test_stop_restores_each_color_mode_and_allows_restart(
    hass: HomeAssistant, attributes: dict[str, Any], expected: dict[str, Any]
) -> None:
    """Restore through the real light schema and leave the scene startable."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", attributes)
    await manager.start(_repeating_config("Spooky", ["light.one"]))
    await asyncio.sleep(0)
    calls.clear()

    await manager.stop({CONF_NAME: "Spooky"})
    await hass.async_block_till_done()

    assert calls == [{"entity_id": ["light.one"], "transition": 1, **expected}]
    assert "Spooky" not in manager.animations
    assert manager.light_owner == {}
    assert manager.states == {}

    await manager.start(_repeating_config("Spooky", ["light.one"]))
    assert "Spooky" in manager.animations
    await manager.stop({CONF_NAME: "Spooky"})


async def test_restart_keeps_original_state_for_final_restore(hass: HomeAssistant) -> None:
    """Restore the pre-animation color after a same-name restart."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set(
        "light.one", "on", {"color_mode": "rgb", "brightness": 9, "rgb_color": (1, 2, 3)}
    )
    await manager.start(_repeating_config("Spooky", ["light.one"]))
    await asyncio.sleep(0)
    hass.states.async_set(
        "light.one", "on", {"color_mode": "rgb", "brightness": 255, "rgb_color": (255, 0, 0)}
    )

    await manager.start(_repeating_config("Spooky", ["light.one"]))
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert not [call for call in calls if call.get("rgb_color") == (1, 2, 3)]

    calls.clear()
    await manager.stop({CONF_NAME: "Spooky"})
    await hass.async_block_till_done()

    assert calls == [
        {"entity_id": ["light.one"], "transition": 1, "brightness": 9, "rgb_color": (1, 2, 3)}
    ]


async def test_home_assistant_stop_ends_running_animations(hass: HomeAssistant) -> None:
    """Stop animation loops and release lights when Home Assistant stops."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    await manager.start(_repeating_config("Spooky", ["light.one"]))
    await asyncio.sleep(0)
    assert len(animation_tasks("Spooky")) == 1

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert animation_tasks("Spooky") == []
    assert manager.animations == {}
    assert manager.light_owner == {}


async def test_stop_before_first_loop_step_releases_lights(hass: HomeAssistant) -> None:
    """Release lights when a task is cancelled before its first step."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    await manager.start(_repeating_config("Spooky", ["light.one"]))

    await manager.stop({CONF_NAME: "Spooky"})

    assert manager.animations == {}
    assert manager.light_owner == {}
    assert manager.states == {}


@pytest.mark.parametrize(
    ("low_priority", "high_priority"),
    [(1, 10), (PRIORITY_MIN, PRIORITY_MIN + 1)],
    ids=["ordinary", "extreme_negative"],
)
async def test_priority_handoff_applies_color_then_restores_original(
    hass: HomeAssistant, low_priority: int, high_priority: int
) -> None:
    """Hand a light to the next priority and restore it after the final owner."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    low = await _start(
        manager,
        "Low",
        ["light.one"],
        priority=low_priority,
        animate_color=False,
        colors=[{"color_type": "rgb_color", "color": (0, 255, 0)}],
    )
    await _start(manager, "High", ["light.one"], priority=high_priority)
    calls.clear()

    await manager.stop({CONF_NAME: "High"})
    await hass.async_block_till_done()

    assert manager.light_owner["light.one"] is low
    assert [call["rgb_color"] for call in calls] == [(0, 255, 0)]

    calls.clear()
    await manager.stop({CONF_NAME: "Low"})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(1, 2, 3)]
    assert manager.light_owner == {}


async def test_priority_handoff_applies_color_despite_one_change_per_tick(
    hass: HomeAssistant,
) -> None:
    """Send the returning scene's color on handoff even if a tick would change brightness only."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _start(
        manager,
        "Low",
        ["light.one"],
        priority=1,
        animate_color=False,
        colors=[
            {
                "color_type": "rgb_color",
                "color": (0, 255, 0),
                "brightness": 50,
                "one_change_per_tick": True,
            }
        ],
    )
    await _start(manager, "High", ["light.one"], priority=10)
    calls.clear()

    with patch("custom_components.animated_scenes.animations.randrange", return_value=2):
        await manager.stop({CONF_NAME: "High"})
        await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(0, 255, 0)]
    await manager.stop({CONF_NAME: "Low"})


async def test_external_turn_on_updates_light_from_event_loop(hass: HomeAssistant) -> None:
    """Re-apply the animation when a tracked light is turned back on."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    await manager.start(_repeating_config("Spooky", ["light.one"]))
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    hass.states.async_set("light.one", "off", {})
    await hass.async_block_till_done()
    calls.clear()

    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (9, 9, 9)})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(255, 0, 0)]
    await manager.stop({CONF_NAME: "Spooky"})


async def test_external_turn_on_reapplies_only_the_recorded_owner(hass: HomeAssistant) -> None:
    """Send one update from the owner when equal-priority scenes share a light."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _start(
        manager,
        "First",
        ["light.one"],
        priority=5,
        colors=[{"color_type": "rgb_color", "color": (255, 0, 0)}],
    )
    second = await _start(
        manager,
        "Second",
        ["light.one"],
        priority=5,
        colors=[{"color_type": "rgb_color", "color": (0, 255, 0)}],
    )
    assert manager.light_owner["light.one"] is second
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    hass.states.async_set("light.one", "off", {})
    await hass.async_block_till_done()
    calls.clear()

    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (9, 9, 9)})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(0, 255, 0)]
    await manager.stop({CONF_NAME: "First"})
    await manager.stop({CONF_NAME: "Second"})


async def test_sequence_scene_with_zero_weights_starts_from_switch(hass: HomeAssistant) -> None:
    """Start a sequence scene through its switch even when every color weight is zero."""
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    data = {
        **_full_scene_data(),
        "change_sequence": True,
        "colors": [
            {"color_type": "rgb_color", "color": [255, 0, 0], "weight": 0},
            {"color_type": "rgb_color", "color": [0, 0, 255], "weight": 0},
        ],
    }
    await _setup_scene_entry(hass, data)
    manager = Animations.instance
    assert manager is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
    )
    await hass.async_block_till_done()

    assert "Spooky" in manager.animations
    assert calls[0]["rgb_color"] == (255, 0, 0)
    await manager.stop({CONF_NAME: "Spooky"})


async def test_random_scene_with_zero_weights_is_rejected_by_switch(hass: HomeAssistant) -> None:
    """Keep rejecting all-zero weights when colors are chosen at random."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    data = {
        **_full_scene_data(),
        "colors": [{"color_type": "rgb_color", "color": [255, 0, 0], "weight": 0}],
    }
    await _setup_scene_entry(hass, data)
    manager = Animations.instance
    assert manager is not None

    with pytest.raises(IntegrationError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.animated_scenes_spooky"}, blocking=True
        )
    await hass.async_block_till_done()

    assert manager.animations == {}


def _to_rgb(color_type: str, value: Any) -> tuple[float, float, float]:
    """Convert a light color value to RGB for proximity assertions."""
    if color_type == "rgbw_color":
        return color_rgbw_to_rgb(*value)
    if color_type == "rgbww_color":
        red, green, blue, cold_white, warm_white = value
        return color_rgbww_to_rgb(red, green, blue, cold_white, warm_white, MIN_KELVIN, MAX_KELVIN)
    if color_type == "hs_color":
        return color_hs_to_RGB(*value)
    if color_type == "xy_color":
        return color_xy_to_RGB(*value)
    return color_temperature_to_rgb(value)


@pytest.mark.parametrize(
    ("color_type", "value"),
    [
        ("rgbw_color", (200, 80, 40, 0)),
        ("rgbww_color", (200, 80, 40, 0, 0)),
        ("hs_color", (20.0, 80.0)),
        ("xy_color", (0.5, 0.4)),
        ("color_temp_kelvin", 3000),
    ],
    ids=["rgbw", "rgbww", "hs", "xy", "kelvin"],
)
async def test_nearby_color_sends_valid_nearby_value(
    hass: HomeAssistant, color_type: str, value: Any
) -> None:
    """Send a nearby color in its original format through the light schema."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    with patch(
        "custom_components.animated_scenes.animations.uniform",
        side_effect=lambda low, _high: low,
    ):
        await _start(
            manager,
            "Spooky",
            ["light.one"],
            colors=[{"color_type": color_type, "color": value, "nearby_colors": 1, "weight": 10}],
        )
        await hass.async_block_till_done()

    sent = calls[0][color_type]
    source_rgb = _to_rgb(color_type, value)
    sent_rgb = _to_rgb(color_type, sent)
    assert all(abs(a - b) <= 40 for a, b in zip(source_rgb, sent_rgb, strict=True))
    # The fixed lower-bound perturbation must actually move the color.
    assert sent != (value if isinstance(value, int) else tuple(value))
    await manager.stop({CONF_NAME: "Spooky"})


def _hls(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return the HLS coordinates of a 0-255 RGB color."""
    red, green, blue = (channel / 255.0 for channel in rgb)
    return colorsys.rgb_to_hls(red, green, blue)


async def test_nearby_colors_vary_within_configured_bound(hass: HomeAssistant) -> None:
    """Vary RGB colors across ticks while staying within the nearby_colors bound."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    source = (200, 80, 40)
    animation = await _start(
        manager,
        "Spooky",
        ["light.one"],
        colors=[{"color_type": "rgb_color", "color": source, "nearby_colors": 10, "weight": 10}],
    )
    for _ in range(20):
        await animation.update_lights()
    await hass.async_block_till_done()

    sent = [tuple(call["rgb_color"]) for call in calls]
    source_hls = _hls(source)
    # nearby_colors 10 allows +/-0.10 per HLS channel; allow byte rounding slack.
    bound = 0.10 + 0.02
    for color in sent:
        hue, lightness, saturation = _hls(color)
        hue_distance = abs(hue - source_hls[0])
        assert min(hue_distance, 1 - hue_distance) <= bound
        assert abs(lightness - source_hls[1]) <= bound
        assert abs(saturation - source_hls[2]) <= bound
    assert len(set(sent)) > 1
    assert any(color != source for color in sent)
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("mireds", "expected_kelvin"),
    [(370, 2702), (1000, MIN_KELVIN), (1, MAX_KELVIN)],
    ids=["ordinary", "clamped_warm", "clamped_cool"],
)
async def test_mired_colors_are_sent_as_bounded_kelvin(
    hass: HomeAssistant, mireds: int, expected_kelvin: int
) -> None:
    """Convert legacy mired colors to the Kelvin field Home Assistant accepts."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    await _start(
        manager,
        "Spooky",
        ["light.one"],
        colors=[{"color_type": "color_temp", "color": mireds, "weight": 10}],
    )
    await hass.async_block_till_done()

    assert calls[0]["color_temp_kelvin"] == expected_kelvin
    await manager.stop({CONF_NAME: "Spooky"})


async def test_starting_off_light_sends_one_initial_update(hass: HomeAssistant) -> None:
    """Do not treat the scene's own turn-on as an external light change."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "off")

    await _start(manager, "Spooky", ["light.one"])
    await hass.async_block_till_done()

    assert len(calls) == 2  # Initial update plus the loop's first tick.
    await manager.stop({CONF_NAME: "Spooky"})


async def test_oversized_change_amount_applies_to_lights_added_later(
    hass: HomeAssistant,
) -> None:
    """Use the configured amount once enough active lights exist."""
    manager = _runtime_manager(hass)
    register_light_services(hass)
    for light in ("light.one", "light.two", "light.three"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"], change_amount=2)
    assert animation.get_change_amount() == 1

    await manager.add_lights_to_animation(
        {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two", "light.three"]}
    )

    assert animation.get_change_amount() == 2
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {CONF_NAME: "Spooky", CONF_ANIMATED_SCENE_SWITCH: "switch.spooky"},
            "must be listed but not both",
        ),
        ({}, "must be listed but not both"),
        ({CONF_NAME: "Stopped"}, "is not running"),
    ],
    ids=["both", "neither", "not_running"],
)
async def test_add_lights_rejects_invalid_targets(
    hass: HomeAssistant, data: dict[str, str], message: str
) -> None:
    """Report invalid animation targets with a clear integration error."""
    manager = _runtime_manager(hass)

    with pytest.raises(IntegrationError, match=message):
        await manager.add_lights_to_animation({**data, CONF_LIGHTS: ["light.one"]})


async def test_static_brightness_applies_when_brightness_is_not_animated(
    hass: HomeAssistant,
) -> None:
    """Use the documented top-level brightness when animation is disabled."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)

    await _start(manager, "Spooky", ["light.one"], animate_brightness=False, brightness=50)
    await hass.async_block_till_done()

    assert calls[0]["brightness"] == 50
    await manager.stop({CONF_NAME: "Spooky"})


async def test_same_priority_restart_does_not_flash_lower_scene(hass: HomeAssistant) -> None:
    """Keep ownership through a same-priority restart without a lower-scene flash."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _start(
        manager,
        "Low",
        ["light.one"],
        priority=1,
        animate_color=False,
        colors=[{"color_type": "rgb_color", "color": (0, 255, 0)}],
    )
    await _start(manager, "High", ["light.one"], priority=10)
    calls.clear()

    restarted = await _start(manager, "High", ["light.one"], priority=10)
    await hass.async_block_till_done()

    assert (0, 255, 0) not in [call.get("rgb_color") for call in calls]
    assert manager.light_owner["light.one"] is restarted
    await manager.stop({CONF_NAME: "High"})
    await manager.stop({CONF_NAME: "Low"})


async def test_lowered_priority_restart_hands_off_to_other_scene(hass: HomeAssistant) -> None:
    """Hand a light to the other scene when a restart drops below its priority."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    other = await _start(
        manager,
        "Other",
        ["light.one"],
        priority=5,
        animate_color=False,
        colors=[{"color_type": "rgb_color", "color": (0, 255, 0)}],
    )
    await _start(manager, "High", ["light.one"], priority=10)
    calls.clear()

    await _start(manager, "High", ["light.one"], priority=1)
    await hass.async_block_till_done()

    assert (0, 255, 0) in [call.get("rgb_color") for call in calls]
    assert manager.light_owner["light.one"] is other
    await manager.stop({CONF_NAME: "High"})
    await manager.stop({CONF_NAME: "Other"})


async def test_sequence_ticks_cycle_colors_in_configured_order(hass: HomeAssistant) -> None:
    """Send sequence colors in configured order and wrap after the last one."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    order = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    animation = await _start(
        manager,
        "Spooky",
        ["light.one"],
        change_sequence=True,
        colors=[{"color_type": "rgb_color", "color": color} for color in order],
    )
    await hass.async_block_till_done()
    for _ in range(4):
        await animation.update_lights()
    await hass.async_block_till_done()

    sent = [call["rgb_color"] for call in calls]
    assert len(sent) >= 5
    assert sent == [order[index % len(order)] for index in range(len(sent))]
    await manager.stop({CONF_NAME: "Spooky"})


async def test_ticks_skip_off_lights_when_ignore_off_is_false(hass: HomeAssistant) -> None:
    """Leave a light that was turned off alone on later ticks."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one", "light.two"], ignore_off=False)
    await hass.async_block_till_done()
    hass.states.async_set("light.two", "off")
    await hass.async_block_till_done()
    calls.clear()

    for _ in range(3):
        await animation.update_lights()
    await hass.async_block_till_done()

    assert calls
    assert {tuple(call["entity_id"]) for call in calls} == {("light.one",)}
    await manager.stop({CONF_NAME: "Spooky"})


async def test_ticks_keep_initial_color_when_animate_color_is_off(hass: HomeAssistant) -> None:
    """Set the color once on start and send only brightness on later ticks."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    animation = await _start(manager, "Spooky", ["light.one"], animate_color=False)
    for _ in range(3):
        await animation.update_lights()
    await hass.async_block_till_done()

    initial, *ticks = calls
    assert initial["rgb_color"] == (255, 0, 0)
    assert ticks
    assert all("rgb_color" not in call and call["brightness"] == 255 for call in ticks)
    await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.parametrize(
    ("restore_power", "expected_turn_offs", "expected_state"),
    [(True, [{"entity_id": ["light.one"]}], "off"), (False, [], "on")],
    ids=["restore_power", "keep_power"],
)
async def test_stop_restores_power_of_originally_off_light(
    hass: HomeAssistant,
    restore_power: bool,
    expected_turn_offs: list[dict[str, Any]],
    expected_state: str,
) -> None:
    """Turn an originally-off light back off on stop only when restore_power is set."""
    manager = _runtime_manager(hass)
    turn_offs: list[dict[str, Any]] = []
    register_light_services(hass, turn_offs)
    hass.states.async_set("light.one", "off")
    await _start(manager, "Spooky", ["light.one"], restore_power=restore_power)
    await hass.async_block_till_done()
    light = hass.states.get("light.one")
    assert light is not None
    assert light.state == "on"

    await manager.stop({CONF_NAME: "Spooky"})
    await hass.async_block_till_done()

    assert turn_offs == expected_turn_offs
    light = hass.states.get("light.one")
    assert light is not None
    assert light.state == expected_state


async def test_restart_keeps_switch_and_activity_sensor_on(hass: HomeAssistant) -> None:
    """Keep the switch on and the activity count up through a same-name restart."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    await _setup_scene_entry(hass, _full_scene_data())
    sensor_entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Activity Sensor",
        data={CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR, CONF_NAME: "Activity Sensor"},
    )
    sensor_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sensor_entry.entry_id)
    await hass.async_block_till_done()
    switch_id = "switch.animated_scenes_spooky"
    sensor_id = "sensor.animated_scenes_activity_sensor"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id}, blocking=True)
    await hass.async_block_till_done()
    observed: list[tuple[str, str]] = []

    def _record(event: Event) -> None:
        """Record switch and sensor state writes."""
        new_state = event.data["new_state"]
        if new_state is not None and event.data["entity_id"] in {switch_id, sensor_id}:
            observed.append((event.data["entity_id"], new_state.state))

    hass.bus.async_listen("state_changed", _record)

    await hass.services.async_call(
        DOMAIN, "start_animation", _repeating_config("Spooky", ["light.one"]), blocking=True
    )
    await hass.async_block_till_done()

    assert (switch_id, "off") not in observed
    assert (sensor_id, "0") not in observed
    switch_state = hass.states.get(switch_id)
    sensor_state = hass.states.get(sensor_id)
    assert switch_state is not None
    assert switch_state.state == "on"
    assert sensor_state is not None
    assert sensor_state.state == "1"

    await hass.services.async_call(DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True)
    await hass.async_block_till_done()

    switch_state = hass.states.get(switch_id)
    sensor_state = hass.states.get(sensor_id)
    assert switch_state is not None
    assert switch_state.state == "off"
    assert sensor_state is not None
    assert sensor_state.state == "0"


async def test_restart_skipping_off_light_hands_it_to_lower_scene(hass: HomeAssistant) -> None:
    """Let a lower scene drive a light the restarted scene no longer activates."""
    manager = _runtime_manager(hass)
    calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", LIGHT_ON)
    low = await _start(
        manager,
        "Low",
        ["light.one"],
        priority=50,
        colors=[{"color_type": "rgb_color", "color": (0, 255, 0)}],
    )
    await _start(manager, "High", ["light.one"], priority=100)
    await hass.async_block_till_done()
    hass.states.async_set("light.one", "off", {})
    await hass.async_block_till_done()

    await _start(manager, "High", ["light.one"], priority=100, ignore_off=False)
    await hass.async_block_till_done()
    assert manager.light_owner["light.one"] is low
    calls.clear()

    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (9, 9, 9)})
    await hass.async_block_till_done()

    assert [call["rgb_color"] for call in calls] == [(0, 255, 0)]
    await manager.stop({CONF_NAME: "High"})
    await manager.stop({CONF_NAME: "Low"})
