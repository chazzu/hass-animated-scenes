import asyncio
import logging
from random import choices, randrange, sample, uniform
from typing import List
from config.custom_components.animated_scenes.const import (
    CONF_ANIMATE_BRIGHTNESS,
    CONF_ANIMATE_COLOR,
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_CHANGE_SEQUENCE,
    CONF_COLOR,
    CONF_COLOR_TYPE,
    CONF_COLORS,
    CONF_IGNORE_OFF,
    CONF_NEARBY_COLORS,
    CONF_ONE_CHANGE_PER_TICK,
    CONF_PRIORITY,
    CONF_RESTORE,
    CONF_RESTORE_POWER,
    CONF_TRANSITION,
    CONF_WEIGHT,
)
from homeassistant.const import (
    CONF_LIGHTS,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant as State
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.exceptions import IntegrationError, RequiredParameterMissing
import colorsys

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    VALID_TRANSITION,
)
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

COLOR_GROUP_SCHEMA = {
    vol.Optional(ATTR_BRIGHTNESS, default = 255): vol.Any(
        vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])
    ),
    vol.Optional(CONF_WEIGHT, default=10): vol.Range(min=0, max=255),
    vol.Optional(CONF_ONE_CHANGE_PER_TICK, default=False): bool,
    vol.Optional(CONF_NEARBY_COLORS, default=0): vol.Range(min=0, max=10),
}

START_SERVICE_CONFIG = {
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_IGNORE_OFF, default=True): bool,
    vol.Optional(CONF_RESTORE, default=True): bool,
    vol.Optional(CONF_RESTORE_POWER, default=True): bool,
    vol.Optional(CONF_TRANSITION, default=float(1.0)): vol.Any(
        VALID_TRANSITION, vol.All([VALID_TRANSITION])
    ),
    vol.Optional(CONF_CHANGE_FREQUENCY, default=float(1.0)): vol.Any(
        vol.Coerce(float),
        vol.Range(min=0, max=60),
        vol.All([vol.Coerce(float), vol.Range(min=0, max=60)]),
    ),
    vol.Optional(CONF_CHANGE_AMOUNT, default=1): vol.Any(
        "all",
        vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
        vol.All(vol.Coerce(int), vol.All([vol.Range(min=0, max=65535)])),
    ),
    vol.Optional(CONF_CHANGE_SEQUENCE, default=False): bool,
    vol.Optional(CONF_ANIMATE_BRIGHTNESS, default=True): bool,
    vol.Optional(CONF_ANIMATE_COLOR, default=True): bool,
    vol.Optional(CONF_PRIORITY, default=100): int,
    vol.Required(CONF_LIGHTS): cv.entity_ids,
    vol.Optional(CONF_COLORS, default=[]): vol.All(
        cv.ensure_list,
        [
            vol.Any(
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGB_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 3)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGBW_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 4)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGBWW_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((cv.byte,) * 5)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_XY_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple),
                            vol.ExactSequence((cv.small_float, cv.small_float)),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_HS_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple),
                            vol.ExactSequence(
                                (
                                    vol.All(
                                        vol.Coerce(float), vol.Range(min=0, max=360)
                                    ),
                                    vol.All(
                                        vol.Coerce(float), vol.Range(min=0, max=100)
                                    ),
                                )
                            ),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_COLOR_TEMP,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(int), vol.Range(min=1)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_COLOR_TEMP_KELVIN,
                        vol.Required(CONF_COLOR): cv.positive_int,
                    }
                ).extend(COLOR_GROUP_SCHEMA),
            )
        ],
    ),
}

START_SERVICE_SCHEMA = vol.Schema(START_SERVICE_CONFIG)

STOP_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
    }
)


class Animation:
    def __init__(self, hass, config):
        self._name: str = config.get(CONF_NAME)
        self._active_lights: List[str] = []
        self._animate_brightness: bool = config.get(CONF_ANIMATE_BRIGHTNESS)
        self._animate_color: bool = config.get(CONF_ANIMATE_COLOR)
        self._change_amount: int | "all" = config.get(CONF_CHANGE_AMOUNT)
        self._change_frequency = config.get(CONF_CHANGE_FREQUENCY)
        self._colors = config.get(CONF_COLORS)
        self._current_color_index = 0
        self._hass = hass
        self._ignore_off = config.get(CONF_IGNORE_OFF)
        self._lights: List[str] = config.get(CONF_LIGHTS)
        self._light_status = {}
        self._priority: int = config.get(CONF_PRIORITY)
        self._restore: bool = config.get(CONF_RESTORE)
        self._restore_power: bool = config.get(CONF_RESTORE_POWER)
        self._sequence: bool = config.get(CONF_CHANGE_SEQUENCE)
        self._task = None
        self._transition = config.get(CONF_TRANSITION)
        self._weights = []

        for color in self._colors:
            if "weight" in color:
                self._weights.append(color["weight"])

        self.add_lights(self._lights)

    def add_light(self, entity_id):
        state = self._hass.states.get(entity_id)
        if state.state != "off" and entity_id not in self._active_lights:
            self._active_lights.append(entity_id)
        elif (
            state.state == "off"
            and self._ignore_off
            and entity_id not in self._active_lights
        ):
            self._active_lights.append(entity_id)

    def add_lights(self, ids):
        for light in ids:
            self.add_light(light)
        Animations.instance.store_states(self._active_lights)

    async def animate(self):
        try:
            while True:
                await self.update_lights()
                frequency = self.get_change_frequency()
                await asyncio.sleep(int(frequency))
        except asyncio.CancelledError as err:
            pass

    def build_light_attributes(self, light, initial=False):
        if light in self._light_status and self._light_status[light]["change_one"]:
            color_or_brightness = randrange(1, 2, 1)
            if color_or_brightness == 2:
                return {
                    "entity_id": light,
                    "transition": self.get_transition(),
                    "brightness": self.get_static_or_random(
                        self._light_status[light]["brightness"]
                    ),
                }

        if self._sequence:
            color = self._colors[self._current_color_index]
        else:
            color = self.pick_color()

        attributes = {
            "entity_id": light,
            "transition": self.get_transition(),
        }
        if self._animate_color or initial:
            if CONF_NEARBY_COLORS in color and color[CONF_NEARBY_COLORS] > 0:
                attributes[color[CONF_COLOR_TYPE]] = self.find_nearby_color(color)
            else:
                attributes[color[CONF_COLOR_TYPE]] = color[CONF_COLOR]
        if self._animate_brightness and ATTR_BRIGHTNESS in color:
            attributes["brightness"] = self.get_static_or_random(color[ATTR_BRIGHTNESS])

        if ATTR_BRIGHTNESS in color and color[CONF_ONE_CHANGE_PER_TICK]:
            self._light_status[light] = {
                "change_one": color[CONF_ONE_CHANGE_PER_TICK],
                "brightness": color[ATTR_BRIGHTNESS] or self._brightness,
            }

        return attributes

    def find_nearby_color(self, color):
        selected_color = [
            color[CONF_COLOR][0],
            color[CONF_COLOR][1],
            color[CONF_COLOR][2],
        ]
        modifier = color[CONF_NEARBY_COLORS]
        if color[CONF_COLOR_TYPE] not in [
            ATTR_RGB_COLOR,
            ATTR_RGBW_COLOR,
            ATTR_RGBWW_COLOR,
        ]:
            # _LOGGER.info("Can't find a nearby color for anything except RGB")
            return selected_color
        h, l, s = colorsys.rgb_to_hls(*selected_color)
        hmod = uniform(h - (modifier / 100), h + (modifier / 100))
        lmod = uniform(l - modifier, l + modifier)
        smod = uniform(s - (modifier / 10), s + (modifier / 10))
        r, g, b = map(
            lambda x: 255 if x > 255 else 0 if x < 0 else int(x),
            colorsys.hls_to_rgb(hmod, lmod, smod),
        )
        return [r, g, b]

    def get_change_amount(self):
        return self.get_static_or_random(self._change_amount)

    def get_change_frequency(self):
        return self.get_static_or_random(self._change_frequency)

    def get_transition(self):
        return self.get_static_or_random(self._transition)

    def get_static_or_random(self, value, step=1):
        if isinstance(value, list):
            return randrange(value[0], value[1], step)
        return value

    def pick_color(self):
        color = choices(self._colors, self._weights, k=1)
        return color.pop()

    def pick_lights(self, change_amount):
        if self._ignore_off:
            to_change = []
            randomized_list = sample(self._active_lights, k=change_amount)
            for light in randomized_list:
                state = self._hass.states.get(light)
                if state.state != "off":
                    to_change.append(light)
                if len(to_change) >= change_amount:
                    return to_change
            return to_change
        return sample(self._active_lights, k=change_amount)

    async def update_light(self, entity_id, initial=False):
        if Animations.instance.get_animation_for_light(entity_id) != self:
            return _LOGGER.info(
                "Skipping light %s due to conflicting animation with higher priority, %s",
                entity_id,
                self._name,
            )
        await self._hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            self.build_light_attributes(entity_id, initial),
        )

    async def update_lights(self):
        if self._change_amount == "all":
            change_amount = len(self._lights)
        else:
            change_amount = self.get_static_or_random(self._change_amount)
            if change_amount <= 0:
                return

        lights_to_change = self.pick_lights(change_amount)
        if self._sequence:
            self._current_color_index += 1
        if self._current_color_index >= len(self._colors):
            self._current_color_index = 0

        for light in lights_to_change:
            await self.update_light(light)

    async def start(self):
        for light in self._active_lights:
            await self.update_light(light, True)
        if not self._change_frequency:
            return
        if not self._task:
            self._task = asyncio.get_event_loop().create_task(self.animate())

    async def stop(self):
        self._task.cancel()
        for light in self._active_lights:
            await Animations.instance.release_light(self, light)
        Animations.instance.release_animation(self)


class Animations:
    def __init__(self, hass):
        self.animations: dict[str, Animation] = {}
        self.states: dict[str, State] = {}
        self._external_light_listener = None
        self._light_animations: dict[str, List[Animation]] = {}
        self._light_owner: dict[str, Animation] = {}
        self.hass = hass

    def build_attributes_from_state(self, state):
        attributes = {
            "entity_id": state.entity_id,
            "brightness": state.attributes.get("brightness"),
            "transition": 1,
        }
        exclusive_properties = [
            ATTR_RGB_COLOR,
            ATTR_RGBW_COLOR,
            ATTR_RGBWW_COLOR,
            ATTR_XY_COLOR,
            ATTR_HS_COLOR,
            ATTR_COLOR_TEMP,
            ATTR_COLOR_TEMP_KELVIN,
        ]
        for attr in exclusive_properties:
            value = state.attributes.get(attr)
            if value:
                attributes[attr] = value
                break

        return attributes

    def external_light_change(self, event):
        entity_id = event.data.get("entity_id")
        state = event.data.get("new_state").state
        if state == "on" and event.data.get("old_state").state == "off":
            if entity_id not in self.states:
                self.states[entity_id] = self._hass.states.get(entity_id)
            animation = self.refresh_animation_for_light(entity_id)
            animation.update_light(entity_id)

    def get_animation_by_priority(self, priority) -> Animation | None:
        for animation in self.animations:
            if animation._priority == priority:
                return animation
        return None

    def get_animation_for_light(self, entity_id) -> Animation:
        return self._light_owner[entity_id]

    def refresh_animation_for_light(self, entity_id) -> Animation:
        selected = None
        selected_priority = -(2**31)
        for animation in self._light_animations[entity_id]:
            if (
                entity_id in animation._lights
                and animation._priority > selected_priority
            ):
                selected = animation
                selected_priority = animation._priority
        return selected

    async def start(self, data):
        config = self.validate_start(data)
        id = data.get(CONF_NAME)
        if id in self.animations:
            await self.animations[id].stop()
        animation = Animation(self.hass, config)
        for light in animation._lights:
            if (
                light not in self._light_owner
                or self.get_animation_for_light(light)._priority <= animation._priority
            ):
                self._light_owner[light] = animation
            if light not in self._light_animations:
                self._light_animations[light] = []
            self._light_animations[light].append(animation)
        self.animations[id] = animation
        await animation.start()

    async def stop(self, data):
        config = self.validate_stop(data)
        id = config.get(CONF_NAME)
        if id in self.animations:
            await self.animations[id].stop()

    def refresh_listener(self):
        if self._external_light_listener != None:
            self._external_light_listener()
            self._external_light_listener = None
        if len(self.states) > 0:
            self._external_light_listener = async_track_state_change_event(
                self.hass, self.states.keys(), self.external_light_change
            )

    def release_animation(self, animation: Animation):
        del self.animations[animation._name]
        self.refresh_listener()

    async def release_light(self, animation: Animation, entity_id):
        self._light_animations[entity_id].remove(animation)
        if self._light_owner[entity_id] != animation:
            return _LOGGER.info(
                "Not releasing light %s as it is owned by another animation %s",
                entity_id,
                self._light_owner[entity_id]._name,
            )
        elif len(self._light_animations[entity_id]) > 0:
            self._light_owner[entity_id] = self.refresh_animation_for_light(entity_id)
            return _LOGGER.info(
                "Changing owner from %s to %s",
                animation._name,
                self._light_owner[entity_id]._name,
            )
        if animation._restore:
            previous_state: State = self.states[entity_id]
            if previous_state.state == "on":
                await self.hass.services.async_call(
                    LIGHT_DOMAIN,
                    SERVICE_TURN_ON,
                    self.build_attributes_from_state(previous_state),
                )
            elif animation._restore_power:
                await self.hass.services.async_call(
                    LIGHT_DOMAIN, SERVICE_TURN_OFF, {"entity_id": entity_id}
                )
        del self.states[entity_id]

    def store_state(self, light):
        if light not in self.states:
            self.states[light]: State = self.hass.states.get(light)

    def store_states(self, lights):
        for light in lights:
            self.store_state(light)
        self.refresh_listener()

    def validate_start(self, data):
        try:
            config = START_SERVICE_SCHEMA(dict(data))
        except vol.Invalid as err:
            _LOGGER.error("Error with received configuration, %s", err.error_message)
            raise IntegrationError("Service data did not match schema")
        return config

    def validate_stop(self, data):
        try:
            config = STOP_SERVICE_SCHEMA(dict(data))
        except vol.Invalid as err:
            _LOGGER.error("Error with received configuration, %s", err.error_message)
            raise IntegrationError("Service data did not match schema")
        return config
