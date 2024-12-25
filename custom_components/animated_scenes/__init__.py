"""The Animated Scenes integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .animations import Animations
from .const import CONF_ENTITY_TYPE, DOMAIN, ENTITY_ACTIVITY_SENSOR, ENTITY_SCENE
from .service import add_lights_to_animation, remove_lights, start_animation, stop_animation

_LOGGER: logging.Logger = logging.getLogger(__name__)
PLATFORMS: list = [Platform.SWITCH, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    """Set up the Animated Scenes integration.

    This registers the integration services (start/stop animations and
    add/remove lights) and creates the shared Animations singleton used
    by the platforms.

    Args:
        hass: The Home Assistant instance.
        _: The integration configuration (unused).

    Returns:
        True on successful setup.

    """
    hass.services.async_register(DOMAIN, "start_animation", start_animation)
    hass.services.async_register(DOMAIN, "stop_animation", stop_animation)
    hass.services.async_register(DOMAIN, "remove_lights", remove_lights)
    hass.services.async_register(DOMAIN, "add_lights_to_animation", add_lights_to_animation)
    Animations.instance = Animations(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration.

    Stores a copy of the entry data in hass.data under the integration
    domain and forwards the config entry setup to the appropriate
    platform (switch for scene entities, sensor for activity sensors).

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to set up.

    Returns:
        True when the entry setup has been forwarded successfully.

    """
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    hass.data[DOMAIN][entry.entry_id] = hass_data
    if hass_data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SWITCH])
    else:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms.

    Attempts to unload the platform(s) created for the provided config
    entry. If successful, removes the entry data from hass.data. The
    function determines which platform to unload based on the
    CONF_ENTITY_TYPE stored in the entry data.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to unload.

    Returns:
        True if the platforms were unloaded successfully and the entry
        data removed; False otherwise.

    """
    _LOGGER.info("Unloading: %s", entry.data)
    unload_ok: bool = False
    if entry.data.get(CONF_ENTITY_TYPE, None) == ENTITY_SCENE:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry,
            [Platform.SWITCH],
        )
    if entry.data.get(CONF_ENTITY_TYPE, None) == ENTITY_ACTIVITY_SENSOR:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry,
            [Platform.SENSOR],
        )
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
