"""Sensor for the Animated Scenes integration.

This module provides a sensor entity that reports the number of active
animations and exposes attributes that list active animations and active
lights owned by the integration.
"""

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .animations import Animations
from .const import DEFAULT_ACTIVITY_SENSOR_ICON, DOMAIN, EVENT_NAME_CHANGE, INTEGRATION_NAME

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
        self._attr_should_poll: bool = False
        self._attr_has_entity_name: bool = True
        self._attr_unique_id: str = "animated_scenes_activity_sensor"
        self._attr_name: str = "Activity"
        self._attr_icon: str = DEFAULT_ACTIVITY_SENSOR_ICON
        self._attr_device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, "animated_scenes")},
            "name": INTEGRATION_NAME,
            "manufacturer": INTEGRATION_NAME,
        }
        self.entity_id = ENTITY_ID_FORMAT.format("animated_scenes_activity_sensor")

    async def async_added_to_hass(self) -> None:
        """Subscribe to animation lifecycle events.

        Returns:
            None. Home Assistant removes the listener automatically when this
            entity is removed.

        """
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_NAME_CHANGE, self._handle_animation_event)
        )

    @callback
    def _handle_animation_event(self, _: Event) -> None:
        """Write sensor state immediately after animation activity changes.

        Args:
            _: The animation lifecycle event. The sensor recalculates from the
                manager, so it does not need event payload fields.

        Returns:
            None.

        """
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return the number of active animations."""
        manager = Animations.instance
        if manager:
            return len(manager.animations)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the sensor.

        Returns a mapping containing the list of active animations and the
        list of lights currently owned by animations.
        """
        manager = Animations.instance
        if manager:
            return {
                "active": list(manager.animations.keys()),
                "active_lights": list(manager.light_owner.keys()),
            }
        return {}
