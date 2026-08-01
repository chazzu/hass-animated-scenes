"""The Animated Scenes integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .animations import Animations
from .const import CONF_ENTITY_TYPE, DOMAIN, ENTITY_ACTIVITY_SENSOR, ENTITY_SCENE
from .scene_config import (
    ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA,
    REMOVE_LIGHTS_SERVICE_SCHEMA,
    START_SERVICE_SCHEMA,
    STOP_SERVICE_SCHEMA,
)
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
    hass.services.async_register(
        DOMAIN,
        "start_animation",
        start_animation,
        schema=START_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "stop_animation",
        stop_animation,
        schema=STOP_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "remove_lights",
        remove_lights,
        schema=REMOVE_LIGHTS_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "add_lights_to_animation",
        add_lights_to_animation,
        schema=ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA,
    )
    Animations.instance = Animations(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration.

    Stores a copy of the entry data on the entry runtime data and forwards
    the config entry setup to the appropriate platform (switch for scene
    entities, sensor for activity sensors).

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to set up.

    Returns:
        True when the entry setup has been forwarded successfully.

    """
    if Animations.instance is None:
        Animations.instance = Animations(hass)
    entry.runtime_data = dict(entry.data)
    if entry.runtime_data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SWITCH])
    else:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy entries to persist their runtime entity type.

    Args:
        hass: Home Assistant instance managing the entry.
        entry: Config entry to migrate.

    Returns:
        True when the entry is supported and migration completed.

    """
    if entry.version > 2:
        return False
    data = dict(entry.data)
    data.setdefault(CONF_ENTITY_TYPE, ENTITY_SCENE)
    hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms.

    Attempts to unload the platform(s) created for the provided config
    entry. The function determines which platform to unload based on the
    CONF_ENTITY_TYPE stored in the entry data.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to unload.

    Returns:
        True if the platforms were unloaded successfully; False otherwise.

    """
    _LOGGER.info("Unloading: %s", entry.data)
    manager = Animations.instance
    unload_ok: bool = False
    entity_type = entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE)
    if entity_type == ENTITY_SCENE:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry,
            [Platform.SWITCH],
        )
    if entity_type == ENTITY_ACTIVITY_SENSOR:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry,
            [Platform.SENSOR],
        )
    if unload_ok and manager and entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE:
        name = entry.data.get("name")
        if name:
            await manager.stop_by_name(name)
    return unload_ok
