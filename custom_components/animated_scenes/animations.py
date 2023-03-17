import logging
from typing import List
from homeassistant.core import HomeAssistant as hass, State
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.exceptions import IntegrationError, RequiredParameterMissing

from homeassistant.components.light import (
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    COLOR_GROUP,
    VALID_BRIGHTNESS,
    VALID_TRANSITION,
)
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

START_SERVICE = vol.Schema({
    vol.Required("unique_id"): cv.string,
    vol.Optional("ignore_off", default=True): bool,
    vol.Optional("restore", default=True): bool,
    vol.Optional("restore_power", default=True): bool,
    vol.Optional("transition", default=1): VALID_TRANSITION,
    vol.Optional("change_frequency", default=1.0): float,
    vol.Optional("change_amount", default=1): vol.Any('all', int),
    vol.Optional("change_sequence", default=False): bool,
    vol.Optional("animate_brightness", default=True): bool,
    vol.Optional("animate_color", default=True): bool,
    vol.Optional("priority", default=100): int,
    vol.Required("lights"): cv.entity_ids,
    vol.Optional("colors", default=[]): vol.All(cv.ensure_list, [
        vol.Schema({
            vol.Required("brightness"): vol.All(vol.Schema({
                vol.Required("minimum_brightness", default=255): VALID_BRIGHTNESS,
                vol.Required("maximum_brightness", default=255): VALID_BRIGHTNESS
            })),
            vol.Optional("weight", default=10): int,
            vol.Optional("one_change", default=False): bool,
            vol.Required("color"): vol.Schema({
                vol.Exclusive(ATTR_COLOR_TEMP, COLOR_GROUP): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                ),
                vol.Exclusive(ATTR_COLOR_TEMP_KELVIN, COLOR_GROUP): cv.positive_int,
                vol.Exclusive(ATTR_KELVIN, COLOR_GROUP): cv.positive_int,
                vol.Exclusive(ATTR_HS_COLOR, COLOR_GROUP): vol.All(
                    vol.Coerce(tuple),
                    vol.ExactSequence(
                        (
                            vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
                            vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                        )
                    ),
                ),
                vol.Exclusive(ATTR_RGB_COLOR, COLOR_GROUP): vol.All(
                    vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 3)
                ),
                vol.Exclusive(ATTR_RGBW_COLOR, COLOR_GROUP): vol.All(
                    vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 4)
                ),
                vol.Exclusive(ATTR_RGBWW_COLOR, COLOR_GROUP): vol.All(
                    vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 5)
                ),
                vol.Exclusive(ATTR_XY_COLOR, COLOR_GROUP): vol.All(
                    vol.Coerce(tuple), vol.ExactSequence((cv.small_float, cv.small_float))
                )
            })
        })
    ])
})

class Animation:
  def __init__(self, config):
    self.unique_id: str = config.unique_id
    self.lights: List[str] = config.lights
  
  def update_light(entity_id):
    _LOGGER.info("Updating light", entity_id)

class Animations:
  def __init__(self):
    self.animations: dict[str, Animation] = {}
    self.states: dict[str, State] = {}
    self._external_light_listener = None

  def external_light_change(self, event):
    entity_id = event.data.get('entity_id')
    state = event.data.get('new_state').state
    if state == 'on' and event.data.get('old_state').state == 'off':
        if entity_id not in self.states:
            self.states[entity_id] = hass.states.get(entity_id)
        animation = self.get_animation_for_light(entity_id)
        animation.update_light(entity_id)

  def get_animation_for_light(self, entity_id) -> Animation:
    selected = None
    selected_priority = -(2**31)
    for animation in self.animations:
      if entity_id in animation.lights and animation.priority > selected_priority:
        selected = animation
        selected_priority = animation.priority
    return selected

  def start(self, data):
    config = self.validate(data)
    self.store_states(config.lights)
    self.animations[data.unique_id] = Animation(config)

  def store_states(self, lights):
    changed = False
    for light in lights:
      if light not in self.states:
        self.states[light]: State = hass.states.get(light)
        changed = True
    if changed:
      if self._external_light_listener:
        self._external_light_listener()
      self._external_light_listener = async_track_state_change_event(self.hass, self.states.keys, self.external_light_change)

  def validate(self, data):
    try:
      config = START_SERVICE(data)
    except vol.Invalid as err:
      _LOGGER.error("Error with received configuration", err)
      raise IntegrationError("Service data did not match schema")
    return config
    

ANIMATIONS = Animations()