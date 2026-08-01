"""Tests for Animated Scenes runtime manager and service setup."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.components.light import ATTR_COLOR_TEMP_KELVIN
from homeassistant.config_entries import ConfigEntry, DiscoveryKey
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, IntegrationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes import (
    async_migrate_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.animated_scenes.animations import (
    Animation,
    Animations,
    _rgb_to_kelvin,
    safe_call,
)
from custom_components.animated_scenes.const import (
    CONF_ANIMATED_SCENE_SWITCH,
    CONF_COLOR,
    CONF_COLOR_TYPE,
    CONF_ENTITY_TYPE,
    CONF_LIGHTS,
    CONF_SKIP_RESTORE,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    ENTITY_SCENE,
    EVENT_NAME_CHANGE,
    EVENT_STATE_UPDATED,
    MIN_KELVIN,
)
from custom_components.animated_scenes.scene_config import (
    ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA,
    REMOVE_LIGHTS_SERVICE_SCHEMA,
    START_SERVICE_SCHEMA,
    STOP_SERVICE_SCHEMA,
)
from custom_components.animated_scenes.service import start_animation

DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})


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


def _store_scene_entry(entry: ConfigEntry) -> None:
    """Store scene entry data in runtime data for unload lifecycle tests."""
    entry.runtime_data = dict(entry.data)


def _runtime_manager(hass: HomeAssistant) -> Animations:
    """Return a runtime manager registered as the active singleton."""
    manager = Animations(hass)
    Animations.instance = manager
    return manager


def _tracked_animation(hass: HomeAssistant, manager: Animations) -> Animation:
    """Return a running animation registered in manager ownership maps."""
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation
    manager.light_owner["light.one"] = animation
    manager._light_animations["light.one"] = [animation]
    manager.store_state("light.one")
    return animation


def test_rgb_to_kelvin_caches_repeated_lookup() -> None:
    """Avoid repeating the expensive kelvin search for the same RGB value."""
    _rgb_to_kelvin.cache_clear()

    _rgb_to_kelvin((255, 128, 64))
    _rgb_to_kelvin((255, 128, 64))

    assert _rgb_to_kelvin.cache_info().hits == 1


def test_repeating_animation_frequency_is_never_zero(hass: HomeAssistant) -> None:
    """Keep every accepted repeating frequency above zero at runtime."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on")

    for change_frequency in (0.1, [0.1, 0.2]):
        config = _animation_config("Repeating", ["light.one"])
        config["change_frequency"] = change_frequency
        animation = Animation(hass, manager.validate_start(config))

        assert all(animation.get_change_frequency() >= 0.1 for _ in range(20))


@pytest.mark.parametrize("kelvin", [2200, 4000, 6200])
def test_kelvin_rgb_round_trip_stays_near_source(kelvin: int) -> None:
    """Keep warm, neutral, and cool conversions near their source temperature."""
    animation = cast("Animation", object.__new__(Animation))

    rgb = animation._convert_to_rgb({CONF_COLOR_TYPE: ATTR_COLOR_TEMP_KELVIN, CONF_COLOR: kelvin})

    assert rgb is not None
    # Integer RGB channels lose temperature precision, especially at the cool
    # end where adjacent kelvin values map to the same bytes.
    assert abs(_rgb_to_kelvin(rgb) - kelvin) <= 500


def test_kelvin_rgb_round_trips_do_not_collapse_to_minimum() -> None:
    """Produce distinct inferred temperatures instead of always returning the minimum."""
    animation = cast("Animation", object.__new__(Animation))
    inferred = {
        _rgb_to_kelvin(rgb)
        for kelvin in (2200, 4000, 6200)
        if (
            rgb := animation._convert_to_rgb(
                {CONF_COLOR_TYPE: ATTR_COLOR_TEMP_KELVIN, CONF_COLOR: kelvin}
            )
        )
        is not None
    }

    assert len(inferred) == 3
    assert inferred != {MIN_KELVIN}


@pytest.mark.asyncio
async def test_services_register_with_schema(hass: HomeAssistant) -> None:
    """Require each public service registration to enforce its shared schema.

    Home Assistant applies the schema passed to ``async_register`` before the
    service handler runs. This protects the runtime manager from receiving
    malformed service data through the public service API.
    """
    assert await async_setup(hass, {}) is True

    registrations = hass.services.async_services_internal()[DOMAIN]

    assert set(registrations) == {
        "start_animation",
        "stop_animation",
        "remove_lights",
        "add_lights_to_animation",
    }
    assert registrations["start_animation"].schema is START_SERVICE_SCHEMA
    assert registrations["stop_animation"].schema is STOP_SERVICE_SCHEMA
    assert registrations["remove_lights"].schema is REMOVE_LIGHTS_SERVICE_SCHEMA
    assert registrations["add_lights_to_animation"].schema is ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA


@pytest.mark.asyncio
async def test_safe_call_logs_home_assistant_service_errors() -> None:
    """Keep animation ticks alive when a Home Assistant service call fails."""
    fake_hass = cast(
        "HomeAssistant",
        SimpleNamespace(
            services=SimpleNamespace(
                async_call=AsyncMock(side_effect=HomeAssistantError("service failed"))
            )
        ),
    )

    await safe_call(fake_hass, "light", "turn_on", {"entity_id": "light.one"})


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_release_light_removes_owner_when_no_successor(hass: HomeAssistant) -> None:
    """Remove all runtime ownership state after the final animation releases a light.

    A released light must not keep stale ``light_owner`` or
    ``_light_animations`` entries because later animations use those maps to
    decide whether a light is already owned.
    """
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation
    manager.light_owner["light.one"] = animation
    manager._light_animations["light.one"] = [animation]
    manager.store_state("light.one")

    with patch.object(
        manager, "refresh_listener", wraps=manager.refresh_listener
    ) as refresh_listener:
        await manager.release_light(animation, "light.one")

    assert "light.one" not in manager.light_owner
    assert "light.one" not in manager._light_animations
    assert "light.one" not in manager.states
    refresh_listener.assert_called_once()


@pytest.mark.asyncio
async def test_release_light_hands_owner_to_next_priority(hass: HomeAssistant) -> None:
    """Transfer ownership to the next-highest-priority animation without restoring.

    When another animation still targets the same light, releasing the current
    owner should update ``light_owner`` and retain the stored original state so
    the final owner can restore it later.
    """
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    low_config = _animation_config("Low", ["light.one"], priority=1)
    low_config["change_frequency"] = 3600
    low = Animation(hass, low_config)
    high = Animation(hass, _animation_config("High", ["light.one"], priority=10))
    manager.animations[low.name] = low
    manager.animations[high.name] = high
    manager.light_owner["light.one"] = high
    manager._light_animations["light.one"] = [low, high]
    manager.store_state("light.one")

    with patch.object(low, "update_light", AsyncMock()) as update_light:
        await manager.release_light(high, "light.one")

    assert manager.light_owner["light.one"] is low
    assert "light.one" in manager.states
    update_light.assert_awaited_once_with("light.one")


@pytest.mark.asyncio
async def test_release_light_hands_off_extreme_negative_priority(
    hass: HomeAssistant,
) -> None:
    """Hand ownership to priorities below the former finite sentinel."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    low = Animation(
        hass,
        manager.validate_start(_animation_config("Low", ["light.one"], priority=-(2**40))),
    )
    high = Animation(
        hass,
        manager.validate_start(_animation_config("High", ["light.one"], priority=-(2**39))),
    )
    manager.animations = {low.name: low, high.name: high}
    manager.light_owner["light.one"] = high
    manager._light_animations["light.one"] = [low, high]
    manager.store_state("light.one")

    await manager.release_light(high, "light.one")

    assert manager.light_owner["light.one"] is low
    assert "light.one" in manager.states


@pytest.mark.asyncio
async def test_release_light_skip_ownership_removes_owner(
    hass: HomeAssistant,
) -> None:
    """Remove ownership when removal skips priority reassignment.

    The ``remove_lights`` service calls ``release_light`` with
    ``skip_ownership=True`` after removing a light from one animation. If
    another animation still tracks that light, the manager must not hand the
    light back to that lower-priority animation.
    """
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    removed = Animation(hass, _animation_config("Removed", ["light.one"], priority=10))
    remaining = Animation(hass, _animation_config("Remaining", ["light.one"], priority=1))
    manager.animations[removed.name] = removed
    manager.animations[remaining.name] = remaining
    manager.light_owner["light.one"] = removed
    manager._light_animations["light.one"] = [remaining, removed]
    manager.store_state("light.one")

    await manager.release_light(removed, "light.one", skip_ownership=True)

    assert "light.one" not in manager.light_owner
    assert manager._light_animations["light.one"] == [remaining]
    assert "light.one" not in manager.states


@pytest.mark.asyncio
async def test_add_lights_to_animation_fires_update_event(hass: HomeAssistant) -> None:
    """Notify event-driven entities after adding lights to a running animation."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    hass.states.async_set("light.two", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation

    events = []
    hass.bus.async_listen(EVENT_NAME_CHANGE, lambda event: events.append(event.data))

    await manager.add_lights_to_animation({CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]})
    await hass.async_block_till_done()

    assert {"animation": "Spooky", "state": EVENT_STATE_UPDATED} in events


@pytest.mark.asyncio
async def test_add_lights_to_animation_updates_refresh_membership(
    hass: HomeAssistant,
) -> None:
    """Keep configured membership synced with runtime ownership maps."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    hass.states.async_set("light.two", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation

    await manager.add_lights_to_animation({CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]})

    assert "light.two" in animation.lights
    assert manager.refresh_animation_for_light("light.two") is animation


@pytest.mark.asyncio
async def test_add_lights_to_animation_deduplicates_runtime_ownership(
    hass: HomeAssistant,
) -> None:
    """Avoid stale ownership entries when the same light is added repeatedly."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    hass.states.async_set("light.two", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation

    await manager.add_lights_to_animation({CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]})
    await manager.add_lights_to_animation({CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]})

    assert animation.lights.count("light.two") == 1
    assert manager._light_animations["light.two"].count(animation) == 1


@pytest.mark.asyncio
async def test_add_lights_to_animation_rejects_missing_switch(
    hass: HomeAssistant,
) -> None:
    """Raise a clean integration error for a missing switch selector."""
    manager = _runtime_manager(hass)

    with pytest.raises(IntegrationError, match="was not found"):
        await manager.add_lights_to_animation(
            {CONF_ANIMATED_SCENE_SWITCH: "switch.missing", CONF_LIGHTS: ["light.two"]}
        )


@pytest.mark.asyncio
async def test_add_lights_to_animation_resolves_renamed_switch_by_config_entry(
    hass: HomeAssistant,
) -> None:
    """Resolve a scene through stable registry identity after a display-name change."""
    manager = _runtime_manager(hass)
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation
    hass.states.async_set("light.two", "on", {"brightness": 100, "color_mode": "rgb"})
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
    hass.states.async_set(
        registry_entry.entity_id,
        "on",
        {"friendly_name": "User Renamed Scene"},
    )

    await manager.add_lights_to_animation(
        {
            CONF_ANIMATED_SCENE_SWITCH: registry_entry.entity_id,
            CONF_LIGHTS: ["light.two"],
        }
    )

    assert "light.two" in animation.lights


@pytest.mark.asyncio
async def test_add_lights_to_animation_rejects_unrelated_switch(
    hass: HomeAssistant,
) -> None:
    """Reject switch entities that are not owned by Animated Scenes."""
    manager = _runtime_manager(hass)
    registry_entry = er.async_get(hass).async_get_or_create(
        "switch",
        "unrelated_integration",
        "unrelated-switch",
        suggested_object_id="unrelated",
    )

    with pytest.raises(IntegrationError, match="does not belong to Animated Scenes"):
        await manager.add_lights_to_animation(
            {
                CONF_ANIMATED_SCENE_SWITCH: registry_entry.entity_id,
                CONF_LIGHTS: ["light.two"],
            }
        )


@pytest.mark.asyncio
async def test_add_lights_tracks_only_lights_that_become_active(hass: HomeAssistant) -> None:
    """Exclude missing and ignored-off additions from ownership maps."""
    manager = _runtime_manager(hass)
    animation = _tracked_animation(hass, manager)
    animation._ignore_off = False
    hass.states.async_set("light.off", "off")

    await manager.add_lights_to_animation(
        {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.missing", "light.off"]}
    )

    assert "light.missing" not in manager.light_owner
    assert "light.off" not in manager.light_owner
    assert "light.missing" not in manager._light_animations
    assert "light.off" not in manager._light_animations

    hass.states.async_set("light.off", "on")
    await manager.add_lights_to_animation(
        {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.missing", "light.off"]}
    )

    assert manager.light_owner["light.off"] is animation
    assert "light.missing" not in manager.light_owner


@pytest.mark.asyncio
async def test_remove_lights_fires_update_event(hass: HomeAssistant) -> None:
    """Notify event-driven entities after removing lights from animations."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation
    manager.light_owner["light.one"] = animation
    manager._light_animations["light.one"] = [animation]

    events = []
    hass.bus.async_listen(EVENT_NAME_CHANGE, lambda event: events.append(event.data))

    with patch.object(manager, "release_light", AsyncMock()) as release_light:
        await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})
    await hass.async_block_till_done()

    release_light.assert_awaited_once_with(animation, "light.one", True, True)
    assert {"animation": "Spooky", "state": EVENT_STATE_UPDATED} in events


@pytest.mark.asyncio
async def test_remove_lights_updates_refresh_membership(hass: HomeAssistant) -> None:
    """Remove released lights from configured membership used for refresh."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(hass, _animation_config("Spooky", ["light.one"]))
    manager.animations[animation.name] = animation
    manager.light_owner["light.one"] = animation
    manager._light_animations["light.one"] = [animation]

    with patch.object(manager, "release_light", AsyncMock()):
        await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})

    assert "light.one" not in animation.lights


@pytest.mark.asyncio
async def test_remove_lights_removes_overlapping_light_from_every_animation(
    hass: HomeAssistant,
) -> None:
    """Remove an overlapping light from all priorities and future updates."""
    manager = _runtime_manager(hass)
    for light in ("light.one", "light.low", "light.high"):
        hass.states.async_set(light, "on", {"brightness": 100, "color_mode": "rgb"})
    low = Animation(
        hass,
        manager.validate_start(_animation_config("Low", ["light.one", "light.low"], priority=1)),
    )
    high = Animation(
        hass,
        manager.validate_start(_animation_config("High", ["light.one", "light.high"], priority=10)),
    )
    manager.animations = {low.name: low, high.name: high}
    for animation in (low, high):
        for light in animation.lights:
            manager._track_animation_light(animation, light)
    manager.store_state("light.one")

    await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()) as safe_call:
        await asyncio.gather(low.update_lights(), high.update_lights())

    assert "light.one" not in low.lights
    assert "light.one" not in high.lights
    assert "light.one" not in manager._light_animations
    assert "light.one" not in manager.light_owner
    assert all(call.args[3]["entity_id"] != "light.one" for call in safe_call.await_args_list)


@pytest.mark.asyncio
async def test_remove_lights_restore_event_ignores_untracked_light(
    hass: HomeAssistant,
) -> None:
    """Ignore restoration events after removal has cleared light tracking."""
    manager = _runtime_manager(hass)
    animation = _tracked_animation(hass, manager)
    restore_event = SimpleNamespace(
        data={
            "entity_id": "light.one",
            "old_state": SimpleNamespace(state="off"),
            "new_state": SimpleNamespace(state="on"),
        }
    )

    async def restore_with_state_event(*_: object) -> None:
        """Deliver the restoration state event during the service call."""
        await manager._handle_external_light_change(cast("Any", restore_event))

    with patch(
        "custom_components.animated_scenes.animations.safe_call",
        side_effect=restore_with_state_event,
    ):
        await manager.remove_lights({CONF_LIGHTS: ["light.one"]})

    assert animation.get_active_lights() == []
    assert "light.one" not in manager.states
    assert "light.one" not in manager.light_owner
    assert "light.one" not in manager._light_animations


@pytest.mark.asyncio
async def test_start_clamps_oversized_change_amount(hass: HomeAssistant) -> None:
    """Normalize service change_amount before the animation loop can sample lights."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})

    await manager.start(
        {
            **_animation_config("Spooky", ["light.one"]),
            "change_amount": 2,
        }
    )

    assert manager.animations["Spooky"].get_change_amount() == 1
    await manager.stop({"name": "Spooky"})


@pytest.mark.parametrize(("restore", "expected_calls"), [(True, 2), (False, 1)])
@pytest.mark.asyncio
async def test_one_shot_release_honors_restore_setting(
    hass: HomeAssistant, restore: bool, expected_calls: int
) -> None:
    """Apply one initial update and restore only when configured to do so."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    config = _animation_config("One Shot", ["light.one"])
    config["change_frequency"] = 0
    config["restore"] = restore

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()) as safe_call:
        await manager.start(config)

    assert safe_call.await_count == expected_calls
    assert safe_call.await_args_list[0].args[3]["entity_id"] == "light.one"
    if restore:
        assert safe_call.await_args_list[-1].args[3]["brightness"] == 100
    assert manager.animations == {}


@pytest.mark.asyncio
async def test_start_tracks_only_active_lights_across_restart(hass: HomeAssistant) -> None:
    """Avoid stale ownership for missing and ignored-off configured lights."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.active", "on")
    hass.states.async_set("light.off", "off")
    config = _animation_config("Spooky", ["light.active", "light.off", "light.missing"])
    config["ignore_off"] = False

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()):
        await manager.start(config)

        assert set(manager.light_owner) == {"light.active"}
        assert set(manager._light_animations) == {"light.active"}

        await manager.stop({CONF_NAME: "Spooky"})
        hass.states.async_set("light.off", "on")
        await manager.start(config)

        assert set(manager.light_owner) == {"light.active", "light.off"}
        assert "light.missing" not in manager._light_animations

        await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.asyncio
async def test_startup_failure_rolls_back_runtime_state(hass: HomeAssistant) -> None:
    """Roll back exact ownership and listener state when initial startup fails."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})

    with (
        patch.object(Animation, "start", AsyncMock(side_effect=RuntimeError("startup failed"))),
        pytest.raises(RuntimeError, match="startup failed"),
    ):
        await manager.start(_animation_config("Spooky", ["light.one"]))

    assert manager.animations == {}
    assert manager.light_owner == {}
    assert manager._light_animations == {}
    assert manager.states == {}
    assert manager._external_light_listener is None


@pytest.mark.asyncio
async def test_update_skips_light_removed_after_tick_selection(hass: HomeAssistant) -> None:
    """Tolerate ownership removal after a tick selects its lights."""
    manager = _runtime_manager(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(
        hass,
        manager.validate_start(_animation_config("Spooky", ["light.one", "light.two"])),
    )
    manager.animations[animation.name] = animation
    for light in animation.lights:
        manager._track_animation_light(animation, light)
    selected_update_started = asyncio.Event()
    continue_selected_update = asyncio.Event()
    original_update_light = animation.update_light

    async def pause_removed_light(entity_id: str, initial: bool = False) -> None:
        """Pause the selected light until its ownership has been removed."""
        if entity_id == "light.one":
            selected_update_started.set()
            await continue_selected_update.wait()
        await original_update_light(entity_id, initial)

    with (
        patch.object(animation, "update_light", side_effect=pause_removed_light),
        patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()),
    ):
        update_task = asyncio.create_task(animation.update_lights())
        await selected_update_started.wait()
        await manager.remove_lights({CONF_LIGHTS: ["light.one"], CONF_SKIP_RESTORE: True})
        continue_selected_update.set()
        await update_task

    assert manager.animations["Spooky"] is animation
    assert animation.get_active_lights() == ["light.two"]


@pytest.mark.asyncio
async def test_concurrent_same_name_start_replaces_only_after_startup(
    hass: HomeAssistant,
) -> None:
    """Serialize same-name starts and keep stale cleanup from removing the replacement."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
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
        assert original._task is not None
        assert original._task.done()
        assert replacement._task is not None
        assert not replacement._task.done()

        await original.release()

        assert manager.animations["Spooky"] is replacement
        await manager.stop({CONF_NAME: "Spooky"})


@pytest.mark.asyncio
async def test_remove_final_light_waits_for_startup_and_leaves_no_empty_task(
    hass: HomeAssistant,
) -> None:
    """Serialize final-light removal until startup can create and stop its task."""
    manager = _runtime_manager(hass)
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
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
    assert animation._task is not None
    assert animation._task.done()
    assert manager.animations == {}


@pytest.mark.asyncio
async def test_update_lights_clamps_change_amount_to_active_lights(
    hass: HomeAssistant,
) -> None:
    """Clamp runtime sampling after the active light set changes."""
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})
    animation = Animation(
        hass,
        {
            **_animation_config("Spooky", ["light.one"]),
            "change_amount": 3,
        },
    )

    with patch.object(animation, "update_light", AsyncMock()) as update_light:
        await animation.update_lights()

    update_light.assert_awaited_once_with("light.one")


@pytest.mark.asyncio
@pytest.mark.parametrize("change_amount", ["3", "[1, 3]"])
async def test_start_service_accepts_text_change_amount(
    hass: HomeAssistant,
    change_amount: str,
) -> None:
    """Accept change_amount values submitted by the text service selector."""
    await async_setup(hass, {})
    assert Animations.instance is not None
    manager = Animations.instance
    hass.states.async_set("light.one", "on", {"brightness": 100, "color_mode": "rgb"})

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


@pytest.mark.asyncio
async def test_manager_stop_by_name_releases_running_animation(hass: HomeAssistant) -> None:
    """Release a named animation without requiring service-call validation.

    Config-entry unload already has a trusted entry title/name, so it should be
    able to release the matching runtime animation directly instead of
    fabricating service data for the public ``stop_animation`` handler.
    """
    manager = _runtime_manager(hass)
    _tracked_animation(hass, manager)

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()):
        await manager.stop_by_name("Spooky")

    assert manager.animations == {}
    assert manager.states == {}
    assert manager.light_owner == {}
    assert manager._light_animations == {}


@pytest.mark.asyncio
async def test_manager_stop_by_name_cancels_running_animation_task(hass: HomeAssistant) -> None:
    """Stop the running task before releasing an animation by name."""
    manager = _runtime_manager(hass)
    animation = _tracked_animation(hass, manager)
    animation._weights = [10]

    with patch("custom_components.animated_scenes.animations.safe_call", AsyncMock()):
        await animation.start()

    try:
        assert animation._task is not None

        await manager.stop_by_name("Spooky")

        assert animation._task.done()
        assert manager.animations == {}
    finally:
        if animation._task is not None and not animation._task.done():
            animation._task.cancel()
            with suppress(asyncio.CancelledError, KeyError):
                await animation._task


@pytest.mark.asyncio
async def test_unload_entry_stops_scene_animation(hass: HomeAssistant) -> None:
    """Release a running scene animation before unloading its config entry.

    A scene entity can be removed or reloaded while its animation is active.
    Unload must release runtime state so it does not continue controlling lights
    after Home Assistant removes the config entry's platform entity.
    """
    manager = _runtime_manager(hass)
    animation = AsyncMock()
    animation.name = "Spooky"
    manager.animations["Spooky"] = animation
    entry = _scene_entry()
    _store_scene_entry(entry)

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True

    animation.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_unload_entry_handles_animation_release_cleanup(hass: HomeAssistant) -> None:
    """Avoid double-stop or double-delete when a stopped animation releases itself.

    Real animations remove themselves from ``manager.animations`` during their
    stop/release path. Last-entry unload must tolerate that self-cleanup before
    leaving the service runtime available for service-only usage.
    """

    class ReleasingAnimation(Animation):
        """Animation stub that follows the real manager release contract."""

        def __init__(self, manager: Animations) -> None:
            """Store the manager and initialize stop accounting.

            Args:
                manager: Runtime manager that owns this stub animation.

            """
            self.manager = manager
            self.stop_count = 0

        @property
        def name(self) -> str:
            """Return the animation name used by the runtime manager."""
            return "Spooky"

        async def release(self) -> None:
            """Record one release call and release from the manager.

            Returns:
                None. The method mirrors the real animation path that calls
                ``release_animation`` before control returns to unload cleanup.

            """
            self.stop_count += 1
            self.manager.release_animation(self)

    manager = _runtime_manager(hass)
    animation = ReleasingAnimation(manager)
    manager.animations["Spooky"] = animation
    entry = _scene_entry()
    _store_scene_entry(entry)

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True

    assert animation.stop_count == 1
    assert manager.animations == {}
    assert Animations.instance is manager


@pytest.mark.asyncio
async def test_setup_entry_recreates_manager_after_last_entry_unload(
    hass: HomeAssistant,
) -> None:
    """Recreate the runtime manager when a reload sets up the entry again."""
    Animations.instance = None
    entry = _scene_entry()
    with patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()):
        assert await async_setup_entry(hass, entry) is True

    assert Animations.instance is not None


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


@pytest.mark.asyncio
async def test_legacy_scene_setup_and_unload_use_switch_default(hass: HomeAssistant) -> None:
    """Set up and unload legacy scene entries without persisted entity type."""
    manager = _runtime_manager(hass)
    animation = AsyncMock()
    animation.name = "Legacy"
    manager.animations["Legacy"] = animation
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy",
        data={CONF_NAME: "Legacy"},
        entry_id="legacy",
    )
    entry.add_to_hass(hass)

    with (
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as forward,
        patch.object(
            hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
        ) as unload,
    ):
        assert await async_setup_entry(hass, entry) is True
        assert await async_unload_entry(hass, entry) is True

    forward.assert_awaited_once_with(entry, [Platform.SWITCH])
    unload.assert_awaited_once_with(entry, [Platform.SWITCH])
    animation.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_service_still_works_after_last_entry_unload(
    hass: HomeAssistant,
) -> None:
    """Keep public services active after the final config entry unloads."""
    manager = _runtime_manager(hass)
    animation = AsyncMock()
    animation.name = "Spooky"
    manager.animations["Spooky"] = animation
    entry = _scene_entry()
    _store_scene_entry(entry)

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True

    with patch.object(manager, "start", AsyncMock()) as manager_start:
        await start_animation(ServiceCall(hass, DOMAIN, "start_animation", {CONF_NAME: "Manual"}))

    animation.release.assert_awaited_once()
    manager_start.assert_awaited_once_with({CONF_NAME: "Manual"})
    assert Animations.instance is manager


@pytest.mark.asyncio
async def test_unload_entry_keeps_animation_when_platform_unload_fails(
    hass: HomeAssistant,
) -> None:
    """Keep runtime animation active when Home Assistant cannot unload the entry.

    If platform unload fails, Home Assistant still considers the config entry
    loaded. Runtime cleanup must therefore wait until ``async_unload_platforms``
    succeeds.
    """
    manager = _runtime_manager(hass)
    animation = AsyncMock()
    animation.name = "Spooky"
    manager.animations["Spooky"] = animation
    entry = _scene_entry()
    _store_scene_entry(entry)

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert await async_unload_entry(hass, entry) is False

    animation.stop.assert_not_awaited()
    assert entry.runtime_data["name"] == "Spooky"
