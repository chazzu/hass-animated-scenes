"""Tests for Animated Scenes activity sensor."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.const import (
    CONF_ENTITY_TYPE,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    INTEGRATION_NAME,
)
from custom_components.animated_scenes.sensor import AnimatedScenesSensor

from .helpers import register_light_services

SENSOR_ID = "sensor.animated_scenes_activity_sensor"


def test_sensor_exposes_animated_scenes_device_info(hass: HomeAssistant) -> None:
    """Group activity sensor entities under the Animated Scenes device."""
    sensor = AnimatedScenesSensor(hass)

    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "animated_scenes")},
        "name": INTEGRATION_NAME,
        "manufacturer": INTEGRATION_NAME,
    }


async def test_activity_sensor_follows_animation_lifecycle(hass: HomeAssistant) -> None:
    """Update the entity state as soon as animations start and stop."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Activity Sensor",
        data={CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR, "name": "Activity Sensor"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.data[DOMAIN]
    assert manager is not None
    register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})

    await manager.start(
        {
            "name": "Spooky",
            "lights": ["light.one"],
            "colors": [{"color_type": "rgb_color", "color": [255, 0, 0]}],
            "change_frequency": 60,
        }
    )
    await hass.async_block_till_done()
    running = hass.states.get(SENSOR_ID)
    assert running is not None
    assert running.state == "1"
    assert running.attributes["active"] == ["Spooky"]
    assert running.attributes["active_lights"] == ["light.one"]

    await manager.stop({"name": "Spooky"})
    await hass.async_block_till_done()
    stopped = hass.states.get(SENSOR_ID)
    assert stopped is not None
    assert stopped.state == "0"
