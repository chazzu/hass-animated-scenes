from .animations import (
    Animations,
)
from .const import *

# from homeassistant.components.animated_scenes.animations import Animations
# from homeassistant.components.animated_scenes.const import *


from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import SensorEntity

from homeassistant.const import CONF_NAME

DEPENDENCIES = ["animated_scenes"]

# async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
#     animations = Animations.instance
#     async_add_entities([AnimatedScenesSensor(hass, animations)])
#     # return True

# async def async_setup_entry(
#     hass: HomeAssistant,
#     entry: ConfigEntry,
#     async_add_entities: AddEntitiesCallback,
# ) -> None:
#     """Set up the Animated Scenes sensors."""

#     # tm_client = hass.data[DOMAIN][config_entry.entry_id]
#     name = config_entry.data[CONF_NAME]
#     animations: Animations.instance

#     dev = [
#         AnimatedScenesSensor(hass, animations)
#     ]

#     async_add_entities(dev, True)
    
            # def setup_platform(hass, config, add_entities, _unused):
            #     # Set up switches
            #     name = config.get(CONF_NAME)
            #     animations = Animations.instance

            #     dev = [
            #         AnimatedScenesSensor(hass, animations)
            #     ]
            #     add_entities(dev)
    
async def async_setup_entry(hass, config_entry, async_add_devices):
    async_add_devices([AnimatedScenesSensor(hass, Animations.instance)])
    return True


class AnimatedScenesSensor(SensorEntity):
    @property
    def name(self):
        return "Animated Scenes Active"
    
    @property
    def unique_id(self) -> str:
        """Return unique ID for the entity."""
        return self.entity_id

    @property
    def state(self):
        return self._state
        # return len(Animations.instance.animations)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {"active_animations": self._attributes}

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return len(Animations.instance.animations)
        # return len(self._animations.animations)

    def __init__(self, hass, animations):
        self.hass = hass
        self.entity_id = "sensor.animated_scenes_active"
        self._state = 55
        self._attributes = []
        self._animations: Animations = animations
        # self._number_test = 1

    async def async_added_to_hass(self):
        # self._state = 74
        self._attributes = []

    def update(self):
        active_animations = [
            {
                "name": animation.name,
                "lights": animation.lights,
            }
            for animation in Animations.instance.animations.values()
            # for animation in self._animations.animations.values()
        ]

        self._state = len(Animations.instance.animations)
        # self._state = len(self._animations.animations)
        # self._number_test += 1
        # self._state = self._number_test
        self._attributes = active_animations

    # async def async_update(self):
    #     active_animations = [
    #         {
    #             "name": animation.name,
    #             "lights": animation.lights,
    #         }
    #         for animation in Animations.instance.animations.values()
    #         # for animation in self._animations.animations.values()
    #     ]

    #     self._state = len(Animations.instance.animations)
    #     # self._number_test += 1
    #     # self._state = self._number_test
    #     # self._state = len(self._animations.animations)
    #     self._attributes = active_animations

    # async def async_added_to_hass(self) -> None:
    #     """Handle entity which will be added."""

    #     @callback
    #     def update():
    #         """Update the state."""
    #         active_animations = [
    #             {
    #                 "name": animation.name,
    #                 "lights": animation.lights,
    #             }
    #             for animation in Animations.instance.animations.values()
    #             # for animation in self._animations.animations.values()
    #         ]

    #         self._state = len(Animations.instance.animations)
    #         # self._state = len(self._animations.animations)
    #         self._attributes = active_animations
    #         self.async_schedule_update_ha_state(True)

    #     self.async_on_remove(
    #         async_dispatcher_connect(
    #             self.hass, self._tm_client.api.signal_update, update
    #         )
    #     )
