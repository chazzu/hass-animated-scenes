import asyncio
from asyncio import CancelledError
from random import randrange, sample, choices

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import SERVICE_TURN_ON, CONF_UNIQUE_ID
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from . import GLOBAL_SCENES
from .const import *

DEPENDENCIES = ['animated_scenes', 'light']

PLATFORM_SCHEMA = vol.Schema({
    vol.Required(CONF_PLATFORM): 'animated_scenes',
    vol.Required(CONF_UNIQUE_ID, default=""): cv.string,
    vol.Optional(CONF_NAME, default="Animated Scene"): cv.string,
    vol.Optional(CONF_LIGHTS): cv.entity_ids,
    vol.Optional(CONF_IGNORE_OFF, default=True): bool,
    vol.Optional(CONF_RESTORE, default=True): bool,
    vol.Optional(CONF_RESTORE_POWER, default=False): bool,
    vol.Optional(CONF_COLORS, default=[]): vol.All(
        cv.ensure_list, [vol.Any(vol.Schema({
            vol.Required(CONF_COLOR_TYPE): CONF_COLOR_RGB,
            vol.Required(CONF_COLOR): vol.All([vol.Range(min=0, max=255)]),
            vol.Optional(CONF_BRIGHTNESS): vol.Any(vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])),
            vol.Optional(CONF_WEIGHT, default=10): vol.Range(min=0, max=255),
            vol.Optional(CONF_ONE_CHANGE_PER_TICK, default=False): bool
        }), vol.Schema({
            vol.Required(CONF_COLOR_TYPE): CONF_COLOR_XY,
            vol.Required(CONF_COLOR): vol.All([vol.Coerce(float), vol.Range(min=0, max=1)]),
            vol.Optional(CONF_BRIGHTNESS): vol.Any(vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])),
            vol.Optional(CONF_WEIGHT, default=10): vol.Range(min=0, max=255),
            vol.Optional(CONF_ONE_CHANGE_PER_TICK, default=False): bool
        }), vol.Schema({
            vol.Required(CONF_COLOR_TYPE): CONF_COLOR_HS,
            vol.Required(CONF_COLOR): vol.All([vol.Coerce(float), vol.Range(min=0, max=100)]),
            vol.Optional(CONF_BRIGHTNESS): vol.Any(vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])),
            vol.Optional(CONF_WEIGHT, default=10): vol.Range(min=0, max=255),
            vol.Optional(CONF_ONE_CHANGE_PER_TICK, default=False): bool
        }), vol.Schema({
            vol.Required(CONF_COLOR_TYPE): CONF_COLOR_TEMP,
            vol.Required(CONF_COLOR): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
            vol.Optional(CONF_BRIGHTNESS): vol.Any(vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])),
            vol.Optional(CONF_WEIGHT, default=10): vol.Range(min=0, max=255),
            vol.Optional(CONF_ONE_CHANGE_PER_TICK, default=False): bool
        }))]
    ),
    vol.Optional(CONF_TRANSITION, default=1): vol.Any(vol.Range(min=0, max=60), vol.All([vol.Range(min=0, max=60)])),
    vol.Optional(CONF_CHANGE_FREQUENCY): vol.Any(vol.Range(min=0, max=60), vol.All([vol.Range(min=0, max=60)])),
    vol.Optional(CONF_CHANGE_AMOUNT): vol.Any('all', vol.Range(min=0, max=10), vol.All([vol.Range(min=0, max=10)])),
    vol.Optional(CONF_ANIMATE_BRIGHTNESS, default=True): bool,
    vol.Optional(CONF_ANIMATE_COLOR, default=True): bool,
    vol.Optional(CONF_BRIGHTNESS): vol.Any(vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)]))
})


def setup_platform(hass, config, add_entities, _unused):
    # Set up switches
    name = config.get(CONF_NAME)
    lights = config.get(CONF_LIGHTS)
    brightness = config.get(CONF_BRIGHTNESS)
    colors = config.get(CONF_COLORS)
    transition = config.get(CONF_TRANSITION)
    change_frequency = config.get(CONF_CHANGE_FREQUENCY)
    change_amount = config.get(CONF_CHANGE_AMOUNT)
    restore = config.get(CONF_RESTORE)
    ignore_off = config.get(CONF_IGNORE_OFF)
    animate_brightness = config.get(CONF_ANIMATE_BRIGHTNESS)
    animate_color = config.get(CONF_ANIMATE_COLOR)
    restore_power = config.get(CONF_RESTORE_POWER)
    switch = AnimatedSceneSwitch(hass, name, lights, brightness, colors, transition, change_frequency, change_amount,
                                 restore, ignore_off, animate_brightness, animate_color, restore_power)
    add_entities([switch])


def _get_static_or_random(value, step=1):
    if isinstance(value, list):
        return randrange(value[0], value[1], step)
    return value


class AnimatedSceneSwitch(SwitchEntity):
    @property
    def is_on(self) -> bool:
        return self._state


    @property
    def unique_id(self) -> str:
        """Return unique ID for the entity."""
        return self.entity_id

    @property
    def name(self) -> str:
        return self._name

    def __init__(self, hass, name, lights, brightness, colors, transition, change_frequency, change_amount, restore,
                 ignore_off, animate_brightness, animate_color, restore_power):
        self.hass = hass
        self.lights = lights
        self.restore = restore
        self._name = name
        self._brightness = brightness
        self._colors = colors
        self._transition = transition
        self._change_frequency = change_frequency
        self._change_amount = change_amount
        self._state = None
        self._ignore_off = ignore_off
        self._task = None
        self.entity_id = "switch." + slugify("{} {}".format('animated_scene', name))
        self._state_change_listener = None
        self._weights = []
        self._light_status = {}
        self._animate_color = animate_color
        self._animate_brightness = animate_brightness
        self._restore_power = restore_power
        for color in colors:
            if 'weight' in color:
                self._weights.append(color['weight'])
        GLOBAL_SCENES.add_scene(self)

    async def async_turn_on(self, **kwargs: vol.Any) -> None:
        if not self._state:
            self._state = True
            self._state_change_listener = async_track_state_change_event(self.hass, self.lights,
                                                                         self.external_light_change)
            await GLOBAL_SCENES.activate_scene(self)

    async def external_light_change(self, event):
        entity_id = event.data.get('entity_id')
        state = event.data.get('new_state').state
        stored_state = GLOBAL_SCENES.stored_state
        if state == 'on' and event.data.get('old_state').state == 'off':
            if entity_id not in stored_state:
                stored_state[entity_id] = self.hass.states.get(entity_id)
            await self.set_initial_active_state([entity_id])

    async def async_turn_off(self, **kwargs) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._state_change_listener is not None:
            self._state_change_listener()
            self._state_change_listener = None
        self._state = False
        self._light_status = {}
        await GLOBAL_SCENES.deactivate_scene(self)

    async def initialize(self):
        await self.set_initial_active_state(self.lights)
        if not self._change_frequency:
            return
        if not self._task:
            self._task = asyncio.get_event_loop().create_task(self.animate())

    async def animate(self):
        try:
            while self.is_on:
                await self.update_lights()
                frequency = self._get_change_frequency()
                await asyncio.sleep(frequency)
        except CancelledError:
            pass

    async def update_lights(self):
        if self._change_amount == 'all':
            change_amount = len(self.lights)
        else:
            change_amount = _get_static_or_random(self._change_amount)
            if change_amount <= 0:
                return

        lights_to_change = self._pick_lights(change_amount)

        for light in lights_to_change:
            await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_ON, self._build_light_attributes(light))

    def _pick_lights(self, change_amount):
        if self._ignore_off:
            to_change = []
            randomized_list = sample(self.lights, k=change_amount)
            for light in randomized_list:
                state = self.hass.states.get(light)
                if state.state != 'off':
                    to_change.append(light)
                if len(to_change) >= change_amount:
                    return to_change
            return to_change
        return sample(self.lights, k=change_amount)

    def _build_light_attributes(self, light, initial=False):
        if light in self._light_status and self._light_status[light]['change_one']:
            color_or_brightness = randrange(1, 2, 1)
            if color_or_brightness == 2:
                return {
                    'entity_id': light,
                    'transition': self._get_transition(),
                    'brightness': _get_static_or_random(self._light_status[light]['brightness'])
                }

        color = self._pick_color()
        attributes = {
            'entity_id': light,
            'transition': self._get_transition(),
        }
        if self._animate_color or initial:
            attributes[color[CONF_COLOR_TYPE]] = color[CONF_COLOR]
        if self._animate_brightness:
            if CONF_BRIGHTNESS in color:
                attributes['brightness'] = _get_static_or_random(color[CONF_BRIGHTNESS])
            else:
                attributes['brightness'] = _get_static_or_random(self._brightness)

        if CONF_BRIGHTNESS in color and color[CONF_ONE_CHANGE_PER_TICK]:
            self._light_status[light] = {
                'change_one': color[CONF_ONE_CHANGE_PER_TICK],
                'brightness': color[CONF_BRIGHTNESS] or self._brightness
            }

        return attributes

    def _get_change_amount(self):
        return _get_static_or_random(self._change_amount)

    def _get_change_frequency(self):
        return _get_static_or_random(self._change_frequency)

    def _get_transition(self):
        return _get_static_or_random(self._transition)

    def _pick_color(self):
        color = choices(self._colors, self._weights, k=1)
        return color.pop()

    async def set_initial_active_state(self, lights):
        # initial state!
        for light in lights:
            if not self._ignore_off or self.hass.states.get(light).state == 'on':
                await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_ON, self._build_light_attributes(light, True))

