"""Service handlers for the Animated Scenes integration.

Service registration binds each handler to its Home Assistant instance's manager.
"""

import logging

from homeassistant.core import ServiceCall

from .animations import Animations

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def start_animation(manager: Animations, call: ServiceCall) -> None:
    """Start an animation using the provided service call data."""
    _LOGGER.info("Starting animated lights...")
    await manager.start(call.data)


async def stop_animation(manager: Animations, call: ServiceCall) -> None:
    """Stop an animation using the provided service call data."""
    _LOGGER.info("Stopping animated lights...")
    await manager.stop(call.data)


async def remove_lights(manager: Animations, call: ServiceCall) -> None:
    """Remove one or more lights from their animations."""
    _LOGGER.info("Removing lights from animations...")
    await manager.remove_lights(call.data)


async def add_lights_to_animation(manager: Animations, call: ServiceCall) -> None:
    """Add lights to an existing animation using the service data."""
    _LOGGER.info("Adding lights to animation...")
    await manager.add_lights_to_animation(call.data)
