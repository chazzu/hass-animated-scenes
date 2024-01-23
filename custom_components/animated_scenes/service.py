import logging
from .animations import Animations

from homeassistant.core import ServiceCall

_LOGGER = logging.getLogger(__name__)


async def start_animation(call: ServiceCall):
    _LOGGER.info("Starting animated lights...")
    await Animations.instance.start(call.data)


async def stop_animation(call: ServiceCall):
    _LOGGER.info("Stopping animated lights...")
    await Animations.instance.stop(call.data)


async def remove_lights(call: ServiceCall):
    _LOGGER.info("Removing lights from animations...")
    await Animations.instance.remove_lights(call.data)


async def add_lights_to_animation(call: ServiceCall):
    _LOGGER.info("Adding lights to animation...")
    await Animations.instance.add_lights_to_animation(call.data)
