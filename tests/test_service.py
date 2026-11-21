"""Tests for the public Animated Scenes service API."""

from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol

from custom_components.animated_scenes import async_setup
from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.const import CONF_LIGHTS, DOMAIN

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


async def test_service_lifecycle_controls_lights(hass: HomeAssistant) -> None:
    """Start, extend, shrink, and stop a scene through its public services."""
    await async_setup(hass, {})
    manager = Animations.instance
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


async def test_start_service_keeps_legacy_defaults_for_omitted_fields(
    hass: HomeAssistant,
) -> None:
    """Keep existing automations unchanged when they omit optional fields."""
    await async_setup(hass, {})
    manager = Animations.instance
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
