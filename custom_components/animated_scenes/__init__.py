"""The Animated Scenes integration."""
from __future__ import annotations

import asyncio
from .animations import Animations
from .service import (
    add_lights_to_animation,
    remove_lights,
    start_animation,
    stop_animation,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = ["switch", "sensor"]


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
    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
