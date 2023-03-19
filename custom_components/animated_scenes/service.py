import logging
from config.custom_components.animated_scenes.animations import Animations

from homeassistant.core import ServiceCall

_LOGGER = logging.getLogger(__name__)


async def start_animation(call: ServiceCall):
    _LOGGER.info("Starting animated lights...")
    await Animations.instance.start(call.data)


async def stop_animation(call: ServiceCall):
    _LOGGER.info("Stopping animated lights...")
    await Animations.instance.stop(call.data)
