import logging
from config.custom_components.animated_scenes.animations import ANIMATIONS

from homeassistant.core import ServiceCall

_LOGGER = logging.getLogger(__name__)

def start_animation(call: ServiceCall):
    _LOGGER.info("Starting animated lights...")
    ANIMATIONS.start(call.data)

def stop_animation(call: ServiceCall):
    _LOGGER.info("Stopping animated lights...")
