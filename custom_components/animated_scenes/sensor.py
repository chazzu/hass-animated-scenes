import logging

from homeassistant.components.sensor import ENTITY_ID_FORMAT, SensorEntity

from .animations import Animations
from .const import DEFAULT_ACTIVITY_SENSOR_ICON

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, _config, async_add_entities, _discovery_info=None):
    async_add_entities([AnimatedScenesSensor(hass)])


class AnimatedScenesSensor(SensorEntity):
    def __init__(self, hass):
        self._attr_native_unit_of_measurement = "active animation(s)"
        self._attr_state_class = "measurement"
        self._attr_has_entity_name = True
        self._attr_unique_id = "animated_scenes_activity_sensor"
        self._attr_name = "Activity"
        self._attr_icon = DEFAULT_ACTIVITY_SENSOR_ICON
        self.entity_id = ENTITY_ID_FORMAT.format("animated_scenes_activity_sensor")
        self._scan_interval = 3

    @property
    def native_value(self):
        return len(Animations.instance.animations)

    @property
    def extra_state_attributes(self):
        return {
            "active": list(Animations.instance.animations.keys()),
            "active_lights": list(Animations.instance._light_owner.keys()),
        }
