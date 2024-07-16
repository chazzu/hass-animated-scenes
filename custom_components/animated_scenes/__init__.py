"""The Animated Scenes integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .animations import Animations
from .const import DOMAIN
from .service import (
    add_lights_to_animation,
    remove_lights,
    start_animation,
    stop_animation,
)

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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
