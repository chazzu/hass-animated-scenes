"""Sensor for the Animated Scenes integration.

This module provides a sensor entity that reports the number of active
animations and exposes attributes that list active animations and active
lights owned by the integration.
"""

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .animations import Animations
from .const import DEFAULT_ACTIVITY_SENSOR_ICON

_LOGGER: logging.Logger = logging.getLogger(__name__)
ENTITY_ID_FORMAT = Platform.SENSOR + ".{}"


async def async_setup_entry(
    hass: HomeAssistant,
    _: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Animated Scenes sensor entity for a config entry.

    Register a single sensor entity that reports active animations.
    """

    async_add_entities([AnimatedScenesSensor(hass)])


class AnimatedScenesSensor(SensorEntity):
    """Sensor that reports current Animated Scenes activity.

    The sensor's state is the number of active animations. Additional
    attributes include a list of active animation keys and the lights
    currently owned by animations.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the AnimatedScenesSensor entity.

        Set static attributes such as name, unique id and entity id.
        """

        self.hass: HomeAssistant = hass
        self._attr_native_unit_of_measurement: str = "active animation(s)"
        self._attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name: bool = True
        self._attr_unique_id: str = "animated_scenes_activity_sensor"
        self._attr_name: str = "Activity"
        self._attr_icon: str = DEFAULT_ACTIVITY_SENSOR_ICON
        self.entity_id = ENTITY_ID_FORMAT.format("animated_scenes_activity_sensor")
        self._scan_interval: int = 3

    @property
    def native_value(self) -> int:
        """Return the number of active animations."""
        if Animations.instance:
            return len(Animations.instance.animations)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the sensor.

        Returns a mapping containing the list of active animations and the
        list of lights currently owned by animations.
        """

        if Animations.instance:
            return {
                "active": list(Animations.instance.animations.keys()),
                "active_lights": list(Animations.instance.light_owner.keys()),
            }
        return {}
