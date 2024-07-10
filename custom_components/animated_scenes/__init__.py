"""The Animated Scenes integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .animations import Animations
from .const import CONF_ENTITY_TYPE, DOMAIN, ENTITY_ACTIVITY_SENSOR, ENTITY_SCENE
from .service import (
    add_lights_to_animation,
    remove_lights,
    start_animation,
    stop_animation,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict):
    hass.services.async_register(DOMAIN, "start_animation", start_animation)
    hass.services.async_register(DOMAIN, "stop_animation", stop_animation)
    hass.services.async_register(DOMAIN, "remove_lights", remove_lights)
    hass.services.async_register(
        DOMAIN, "add_lights_to_animation", add_lights_to_animation
    )
    Animations.instance = Animations(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    hass.data[DOMAIN][entry.entry_id] = hass_data
    if hass_data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SWITCH])
    else:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.debug(f"[async_unload_entry] entry data: {entry.data}")
    unload_ok = False
    if entry.data.get(CONF_ENTITY_TYPE, None) == ENTITY_SCENE:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, [Platform.SWITCH]
        )
    if entry.data.get(CONF_ENTITY_TYPE, None) == ENTITY_ACTIVITY_SENSOR:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, [Platform.SENSOR]
        )
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
