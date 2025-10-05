"""Service handlers for the Animated Scenes integration.

This module exposes async service entry points that delegate to the
Animations singleton. Each function logs the requested operation and
passes the service call data through to the corresponding Animations
method.
"""

import logging

from homeassistant.core import ServiceCall

from .animations import Animations

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def start_animation(call: ServiceCall) -> None:
    """Start an animation using the provided service call data.

    The service call's data mapping is forwarded to
    `Animations.instance.start`.
    """

    _LOGGER.info("Starting animated lights...")
    if Animations.instance:
        await Animations.instance.start(call.data)


async def stop_animation(call: ServiceCall) -> None:
    """Stop an animation using the provided service call data.

    The service call's data mapping is forwarded to
    `Animations.instance.stop`.
    """

    _LOGGER.info("Stopping animated lights...")
    if Animations.instance:
        await Animations.instance.stop(call.data)


async def remove_lights(call: ServiceCall) -> None:
    """Remove one or more lights from their animations.

    The service call's data mapping is forwarded to
    `Animations.instance.remove_lights`.
    """

    _LOGGER.info("Removing lights from animations...")
    if Animations.instance:
        await Animations.instance.remove_lights(call.data)


async def add_lights_to_animation(call: ServiceCall) -> None:
    """Add lights to an existing animation using the service data.

    Forwards the service call data to
    `Animations.instance.add_lights_to_animation`.
    """

    _LOGGER.info("Adding lights to animation...")
    if Animations.instance:
        await Animations.instance.add_lights_to_animation(call.data)
