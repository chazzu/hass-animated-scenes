"""Tests for the public Animated Scenes service API."""

from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.core import Event, HomeAssistant, callback
import pytest
from pytest_homeassistant_custom_component.common import async_test_home_assistant
import voluptuous as vol

from custom_components.animated_scenes import async_setup
from custom_components.animated_scenes.const import (
    CONF_LIGHTS,
    DOMAIN,
    EVENT_NAME_CHANGE,
    EVENT_STATE_STARTED,
    EVENT_STATE_STOPPED,
    EVENT_STATE_UPDATED,
)

from .helpers import animation_tasks, register_light_services

COLORS = [{"color_type": "rgb_color", "color": [255, 0, 0]}]
ORIGINAL = {"color_mode": "rgb", "brightness": 100, "rgb_color": (1, 2, 3)}


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("start_animation", {CONF_NAME: "Spooky"}),
        ("stop_animation", {}),
        ("remove_lights", {}),
        ("add_lights_to_animation", {CONF_NAME: "Spooky"}),
    ],
)
async def test_services_reject_malformed_data(
    hass: HomeAssistant, service: str, data: dict[str, str]
) -> None:
    """Reject invalid payloads before they reach the animation runtime."""
    await async_setup(hass, {})

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_same_named_scenes_are_isolated_between_hass_instances(hass: HomeAssistant) -> None:
    """Stopping a scene restores only the light on the instance that received the call."""
    data = {
        CONF_NAME: "Spooky",
        CONF_LIGHTS: ["light.one"],
        "colors": COLORS,
        "change_frequency": 3600,
        "change_amount": 0,
        "restore": True,
    }
    await async_setup(hass, {})
    first_calls = register_light_services(hass)
    hass.states.async_set("light.one", "on", ORIGINAL)
    await hass.services.async_call(DOMAIN, "start_animation", data, blocking=True)
    async with async_test_home_assistant() as other:
        try:
            await async_setup(other, {})
            second_calls = register_light_services(other)
            other.states.async_set("light.one", "on", {**ORIGINAL, "rgb_color": (4, 5, 6)})
            await other.services.async_call(DOMAIN, "start_animation", data, blocking=True)
            await other.async_block_till_done()
            second_calls.clear()

            await hass.services.async_call(
                DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True
            )
            await hass.async_block_till_done()
            assert first_calls[-1]["rgb_color"] == (1, 2, 3)
            assert second_calls == []

            await other.services.async_call(
                DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True
            )
            await other.async_block_till_done()
            assert second_calls[-1]["rgb_color"] == (4, 5, 6)
        finally:
            await other.async_stop()


async def test_service_lifecycle_controls_lights(hass: HomeAssistant) -> None:
    """Start, extend, shrink, and stop a scene through its public services."""
    await async_setup(hass, {})
    manager = hass.data[DOMAIN]
    assert manager is not None
    calls = register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", ORIGINAL)

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.one"], "colors": COLORS, "change_frequency": 60},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert calls[0]["rgb_color"] == (255, 0, 0)

    await hass.services.async_call(
        DOMAIN,
        "add_lights_to_animation",
        {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.two"]},
        blocking=True,
    )
    assert set(manager.light_owner) == {"light.one", "light.two"}

    calls.clear()
    await hass.services.async_call(
        DOMAIN, "remove_lights", {CONF_LIGHTS: ["light.two"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert [call["rgb_color"] for call in calls if call["entity_id"] == ["light.two"]] == [
        (1, 2, 3)
    ]

    await hass.services.async_call(DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True)
    await hass.async_block_till_done()
    assert manager.animations == {}
    assert animation_tasks("Spooky") == []


async def test_start_service_uses_shared_defaults_for_omitted_fields(
    hass: HomeAssistant,
) -> None:
    """Keep existing automations unchanged when they omit optional fields."""
    await async_setup(hass, {})
    manager = hass.data[DOMAIN]
    assert manager is not None
    register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", ORIGINAL)

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            CONF_NAME: "Spooky",
            CONF_LIGHTS: ["light.one", "light.two"],
            "colors": COLORS,
            "change_frequency": 60,
        },
        blocking=True,
    )

    animation = manager.animations["Spooky"]
    assert animation.priority == 100
    assert animation.restore_power is True
    assert animation.get_change_amount() == 1
    await manager.stop({CONF_NAME: "Spooky"})


async def test_start_service_accepts_tuple_ranges(hass: HomeAssistant) -> None:
    """Start an animation from tuple ranges, as automations can supply them."""
    await async_setup(hass, {})
    manager = hass.data[DOMAIN]
    assert manager is not None
    register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", ORIGINAL)

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            CONF_NAME: "Spooky",
            CONF_LIGHTS: ["light.one", "light.two"],
            "colors": COLORS,
            "change_frequency": (1800, 3600),
            "transition": (1, 2),
            "change_amount": (1, 2),
        },
        blocking=True,
    )

    animation = manager.animations["Spooky"]
    assert 1800 <= animation.get_change_frequency() <= 3600
    assert 1 <= animation.get_transition() <= 2
    assert 1 <= animation.get_change_amount() <= 2
    await manager.stop({CONF_NAME: "Spooky"})


async def test_start_service_accepts_text_change_amount_range(hass: HomeAssistant) -> None:
    """Start a scene from a text change-amount range through the real service."""
    await async_setup(hass, {})
    manager = hass.data[DOMAIN]
    assert manager is not None
    register_light_services(hass)
    hass.states.async_set("light.one", "on", ORIGINAL)

    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            CONF_NAME: "Spooky",
            CONF_LIGHTS: ["light.one"],
            "colors": COLORS,
            "change_frequency": 60,
            "change_amount": "[1, 3]",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "Spooky" in manager.animations
    await hass.services.async_call(DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priority", 10**20),
        ("priority", 10**400),
        ("brightness", 10**400),
        ("change_amount", 10**400),
        ("transition", 10**400),
        ("change_frequency", [0, 10**400]),
    ],
)
async def test_start_service_rejects_huge_numbers(
    hass: HomeAssistant, field: str, value: object
) -> None:
    """Reject numbers that cannot be converted or stored as invalid service data."""
    await async_setup(hass, {})

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "start_animation",
            {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.one"], "colors": COLORS, field: value},
            blocking=True,
        )
    manager = hass.data[DOMAIN]
    assert manager is not None
    assert manager.animations == {}


def _capture_scene_events(hass: HomeAssistant) -> list[tuple[str, str]]:
    """Record ``(animation, state)`` for every Animated Scenes change event.

    Args:
        hass: Home Assistant test instance.

    Returns:
        A list that grows with each fired ``animated_scenes_change`` event.

    """
    events: list[tuple[str, str]] = []

    @callback
    def _record(event: Event) -> None:
        """Record the animation name and state of one event."""
        events.append((event.data["animation"], event.data["state"]))

    hass.bus.async_listen(EVENT_NAME_CHANGE, _record)
    return events


async def _start_scene(hass: HomeAssistant, frequency: int) -> None:
    """Start the ``Spooky`` scene through the public service.

    Args:
        hass: Home Assistant test instance.
        frequency: The ``change_frequency`` value in seconds.

    """
    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            CONF_NAME: "Spooky",
            CONF_LIGHTS: ["light.one"],
            "colors": COLORS,
            "change_frequency": frequency,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("next_frequency", "expected"),
    [(0, [("Spooky", EVENT_STATE_STOPPED)]), (60, [("Spooky", EVENT_STATE_STARTED)])],
    ids=["one_shot", "repeating"],
)
async def test_restart_fires_single_event(
    hass: HomeAssistant, next_frequency: int, expected: list[tuple[str, str]]
) -> None:
    """Restart into a one-shot fires only stopped; into a repeating scene only started."""
    await async_setup(hass, {})
    register_light_services(hass)
    hass.states.async_set("light.one", "on", ORIGINAL)
    await _start_scene(hass, 60)
    events = _capture_scene_events(hass)

    await _start_scene(hass, next_frequency)

    assert events == expected
    await hass.services.async_call(DOMAIN, "stop_animation", {CONF_NAME: "Spooky"}, blocking=True)


async def test_removing_last_light_fires_stopped_then_updated(hass: HomeAssistant) -> None:
    """Emit stopped followed by updated when the last light leaves a running scene."""
    await async_setup(hass, {})
    register_light_services(hass)
    hass.states.async_set("light.one", "on", ORIGINAL)
    await _start_scene(hass, 60)
    events = _capture_scene_events(hass)

    await hass.services.async_call(
        DOMAIN, "remove_lights", {CONF_LIGHTS: ["light.one"]}, blocking=True
    )
    await hass.async_block_till_done()

    assert events == [("Spooky", EVENT_STATE_STOPPED), ("Spooky", EVENT_STATE_UPDATED)]
