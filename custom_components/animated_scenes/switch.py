from .animations import (
    START_SERVICE_CONFIG,
    Animations,
)

import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.util import slugify
from .const import *

DEPENDENCIES = ["animated_scenes", "light"]

PLATFORM_SCHEMA_PART = vol.Schema(
    {
        vol.Required(CONF_PLATFORM): "animated_scenes",
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA_PART.extend(START_SERVICE_CONFIG)


def setup_platform(hass, config, add_entities, _unused):
    # Set up switches
    name = config.get(CONF_NAME)
    switch = AnimatedSceneSwitch(hass, name, config)
    add_entities([switch])
    
async def async_setup_entry(hass, config_entry, async_add_devices):
	return True


class AnimatedSceneSwitch(SwitchEntity):
    @property
    def is_on(self) -> bool:
        return self._state

    @property
    def unique_id(self) -> str:
        """Return unique ID for the entity."""
        return self.entity_id

    @property
    def name(self) -> str:
        return self._name

    def __init__(self, hass, name, config):
        self.entity_id = "switch." + slugify("{} {}".format("animated_scene", name))
        self.hass = hass
        self._name = name
        self._state = None
        self._config = {key: value for key, value in config.items() if key != 'platform'}

    async def async_turn_on(self, **kwargs: vol.Any) -> None:
        if not self._state:
            self._state = True
            await Animations.instance.start(self._config)

    async def async_turn_off(self, **kwargs) -> None:
        self._state = False
        await Animations.instance.stop({ "name": self._name })