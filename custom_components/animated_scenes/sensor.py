from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from .animations import Animations
from .const import EVENT_NAME_CHANGE, EVENT_STATE_STARTED, EVENT_STATE_STOPPED


async def async_setup_entry(hass, _config, async_add_entities, _discovery_info=None):
    async_add_entities([AnimatedScenesSensor(hass)])


class AnimatedScenesSensor(SensorEntity):
    _attr_native_unit_of_measurement = "active animation(s)"
    _attr_state_class = "measurement"
    _attr_has_entity_name = True
    _attr_unique_id = "animated_scenes_activity_sensor"
    _attr_name = "Activity"

    _active: set = {}

    scan_interval: 3

    @property
    def native_value(self):
        return len(Animations.instance.animations)

    @property
    def extra_state_attributes(self):
        return {
            "active": list(Animations.instance.animations.keys()),
            "active_lights": list(Animations.instance._light_owner.keys()),
        }

    def __init__(self, hass):
        pass
