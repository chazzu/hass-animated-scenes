"""Animated scenes animation engine.

This module provides the Animation and Animations classes which manage
running color/brightness animations for Home Assistant light entities.
It also defines service schemas and helper functions used by the
integration.
"""

from __future__ import annotations

import asyncio
from asyncio import Task
from collections.abc import Callable
import colorsys
import logging
import math
from random import choices, randrange, sample, uniform
from typing import Any

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    VALID_TRANSITION,
    ColorMode,
)
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_BRIGHTNESS,
    CONF_LIGHTS,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State
from homeassistant.exceptions import IntegrationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_RGB_to_hs,
    color_rgb_to_rgbw,
    color_rgb_to_rgbww,
    color_RGB_to_xy,
    color_rgbw_to_rgb,
    color_rgbww_to_rgb,
    color_temperature_to_rgb,
    color_xy_to_RGB,
)

from .const import (
    ATTR_COLOR_TEMP,
    CONF_ANIMATE_BRIGHTNESS,
    CONF_ANIMATE_COLOR,
    CONF_ANIMATED_SCENE_SWITCH,
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_CHANGE_SEQUENCE,
    CONF_COLOR,
    CONF_COLOR_NEARBY_COLORS,
    CONF_COLOR_ONE_CHANGE_PER_TICK,
    CONF_COLOR_TYPE,
    CONF_COLOR_WEIGHT,
    CONF_COLORS,
    CONF_IGNORE_OFF,
    CONF_PRIORITY,
    CONF_RESTORE,
    CONF_RESTORE_POWER,
    CONF_SKIP_RESTORE,
    CONF_TRANSITION,
    EVENT_NAME_CHANGE,
    EVENT_STATE_STARTED,
    EVENT_STATE_STOPPED,
    MAX_KELVIN,
    MIN_KELVIN,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)

COLOR_GROUP_SCHEMA = {
    vol.Optional(CONF_BRIGHTNESS, default=255): vol.Any(
        vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])
    ),
    vol.Optional(CONF_COLOR_WEIGHT, default=10): vol.Range(min=0, max=255),
    vol.Optional(CONF_COLOR_ONE_CHANGE_PER_TICK, default=False): bool,
    # Nearby-colors modifier: 0 disables, 1-10 controls magnitude of change
    vol.Optional(CONF_COLOR_NEARBY_COLORS, default=0): vol.Range(min=0, max=10),
}

START_SERVICE_CONFIG = {
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_IGNORE_OFF, default=True): bool,
    vol.Optional(CONF_RESTORE, default=True): bool,
    vol.Optional(CONF_RESTORE_POWER, default=True): bool,
    vol.Optional(CONF_BRIGHTNESS, default=255): vol.Any(
        vol.Range(min=0, max=255), vol.All([vol.Range(min=0, max=255)])
    ),
    vol.Optional(CONF_TRANSITION, default=1.0): vol.Any(
        VALID_TRANSITION, vol.All([VALID_TRANSITION])
    ),
    vol.Optional(CONF_CHANGE_FREQUENCY): vol.Any(
        vol.Coerce(float),
        vol.Range(min=0, max=60),
        vol.All([vol.Coerce(float), vol.Range(min=0, max=60)]),
    ),
    vol.Optional(CONF_CHANGE_AMOUNT, default=1): vol.Any(
        "all",
        vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
        vol.All(vol.All([vol.Coerce(int), vol.Range(min=0, max=65535)])),
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
                                    vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
                                    vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                                )
                            ),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_COLOR_TEMP,
                        vol.Required(CONF_COLOR): vol.All(vol.Coerce(int), vol.Range(min=1)),
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

ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIGHTS): cv.entity_ids,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_ANIMATED_SCENE_SWITCH): cv.entity_id,
    }
)


REMOVE_LIGHTS_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIGHTS): cv.entity_ids,
        vol.Optional(CONF_SKIP_RESTORE, default=False): bool,
    }
)


def _convert_mireds_to_kelvin(mireds: int) -> int:
    """Convert mireds to kelvin, ensuring the result is within valid bounds."""
    if mireds <= 0:
        raise IntegrationError("Mireds must be a positive integer")
    kelvin = int(1000000 / mireds)
    if kelvin < MIN_KELVIN:
        kelvin = MIN_KELVIN
    elif kelvin > MAX_KELVIN:
        kelvin = MAX_KELVIN
    return kelvin


async def safe_call(hass: HomeAssistant, domain: str, service: str, attr: dict) -> None:
    """Call a Home Assistant service safely, logging exceptions.

    This wrapper calls the given service on the Home Assistant instance
    and logs a warning if the call raises an exception. It intentionally
    suppresses exceptions to avoid stopping animations when a service
    call fails.

    Args:
        hass: Home Assistant instance.
        domain: Service domain (e.g. "light").
        service: Service name (e.g. "turn_on").
        attr: Service data/attributes to pass to the service.

    Returns:
        None

    """
    try:
        await hass.services.async_call(domain, service, attr)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Received an error calling service. %s: %s", type(e).__name__, e)


def _rgb_to_kelvin(rgb: tuple[int, int, int]) -> int:
    """Approximate the kelvin color temperature for an RGB triple.

    This finds the kelvin in [MIN_KELVIN, MAX_KELVIN] whose color_temperature_to_rgb
    result is closest (Euclidean) to the provided RGB. It's not perfect
    but is sufficient for nearby-color perturbations.
    """
    target = tuple(float(c) / 255.0 for c in rgb)

    lo = MIN_KELVIN
    hi = MAX_KELVIN
    best_k = lo
    best_dist = float("inf")
    # coarse search then refine
    for k in range(lo, hi + 1, 100):
        r_f, g_f, b_f = color_temperature_to_rgb(float(k))
        dist = (r_f - target[0]) ** 2 + (g_f - target[1]) ** 2 + (b_f - target[2]) ** 2
        if dist < best_dist:
            best_dist = dist
            best_k = k
    # refine around best_k
    start = max(lo, best_k - 100)
    end = min(hi, best_k + 100)
    for k in range(start, end + 1):
        r_f, g_f, b_f = color_temperature_to_rgb(float(k))
        dist = (r_f - target[0]) ** 2 + (g_f - target[1]) ** 2 + (b_f - target[2]) ** 2
        if dist < best_dist:
            best_dist = dist
            best_k = k
    return best_k


class Animation:
    """Represent a running animation for a set of lights.

    Each Animation instance stores the configuration for the animation,
    the list of lights it controls, and the asyncio task that performs
    the ongoing updates.
    """

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize an Animation.

        Args:
            hass: The Home Assistant instance.
            config: Validated configuration for the animation (from the
                START service schema).

        Returns:
            None

        """
        self._name: str = config[CONF_NAME]
        self._active_lights: list[str] = []
        self._animate_brightness: bool = config[CONF_ANIMATE_BRIGHTNESS]
        self._animate_color: bool = config[CONF_ANIMATE_COLOR]
        self._global_brightness: int | list[int] = config[CONF_BRIGHTNESS]
        self._change_amount: int | list[int] | str = config[CONF_CHANGE_AMOUNT]
        self._change_frequency: int | list[int] = config[CONF_CHANGE_FREQUENCY]
        self._colors: list[dict[str, Any]] = config[CONF_COLORS]
        self._current_color_index: int = 0
        self._hass: HomeAssistant = hass
        self._ignore_off: bool = config[CONF_IGNORE_OFF]
        self._lights: list[str] = config[CONF_LIGHTS]
        self._light_status: dict[str, Any] = {}
        self._priority: int = config[CONF_PRIORITY]
        self._restore: bool = config[CONF_RESTORE]
        self._restore_power: bool = config[CONF_RESTORE_POWER]
        self._sequence: bool = config[CONF_CHANGE_SEQUENCE]
        self._task: Task | None = None
        self._transition: int | list[int] = config[CONF_TRANSITION]
        self._weights: list = []

        self._change_mired_colors_to_kelvin()

        for color in self._colors:
            if "weight" in color:
                self._weights.append(color["weight"])

        self.add_lights(self._lights)

    @property
    def name(self) -> str:
        """Return the animation's configured name."""
        return self._name

    @property
    def lights(self) -> list[str]:
        """Return the list of lights configured for this animation."""
        return self._lights

    @property
    def priority(self) -> int:
        """Return the priority value for this animation."""
        return self._priority

    @property
    def restore(self) -> bool:
        """Whether this animation should restore previous light states."""
        return self._restore

    @property
    def restore_power(self) -> bool:
        """Whether this animation should restore power (turn off) states."""
        return self._restore_power

    def _change_mired_colors_to_kelvin(self) -> None:
        """Convert any colors in mireds to kelvin in place."""
        for color in self._colors[:]:
            if color[CONF_COLOR_TYPE] == ATTR_COLOR_TEMP:
                try:
                    kelvin = _convert_mireds_to_kelvin(color[CONF_COLOR])
                    _LOGGER.debug(
                        "Converted color temp %d mireds to %d kelvin", color[CONF_COLOR], kelvin
                    )
                    color[CONF_COLOR] = kelvin
                    color[CONF_COLOR_TYPE] = ATTR_COLOR_TEMP_KELVIN
                except IntegrationError as e:
                    _LOGGER.warning(
                        "Skipping invalid color temp %d mireds: %s",
                        color[CONF_COLOR],
                        e,
                    )
                    self._colors.remove(color)

    def add_light(self, entity_id: str) -> None:
        """Add a single light to this animation's active list.

        The light is only added if it meets the configured "ignore off"
        policy and is not already present.

        Args:
            entity_id: The entity id of the light to add.

        Returns:
            None

        """
        state = self._hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity %s not found, skipping", entity_id)
            return
        if entity_id not in self._active_lights and (state.state != "off" or self._ignore_off):
            self._active_lights.append(entity_id)

    def add_lights(self, ids: list) -> None:
        """Add multiple lights to the animation and store their states.

        Args:
            ids: Iterable of entity ids to add.

        Returns:
            None

        """
        for light in ids:
            self.add_light(light)
        if Animations.instance:
            Animations.instance.store_states(self._active_lights)

    async def animate(self) -> None:
        """Run the main animation loop.

        This coroutine runs until the animation is removed or the task is
        cancelled. On each iteration it updates the lights and sleeps for
        the configured frequency.

        Returns:
            None

        """
        try:
            if Animations.instance and self._task:
                while self._name in Animations.instance.animations and not self._task.done():
                    await self.update_lights()
                    frequency = self.get_change_frequency()
                    await asyncio.sleep(frequency)
        finally:
            _LOGGER.info("Animation '%s' has been stopped", self._name)
            if Animations.instance and self._name not in Animations.instance.animations:
                _LOGGER.info(
                    "Animation '%s' was removed from list of active animations",
                    self._name,
                )
            elif self._task and self._task.done():
                _LOGGER.info("Animation '%s' was marked as done", self._name)
            await self.release()

    def build_light_attributes(self, light: str, initial: bool = False) -> dict[str, Any]:
        """Build the service data dict to update a light for this animation.

        Args:
            light: The entity id of the light to update.
            initial: If True, mark this as the initial update for the
                animation (affects whether colors/brightness are applied).

        Returns:
            A mapping containing service data like entity_id, transition,
            brightness and color attributes appropriate for the light.

        """
        if light in self._light_status and self._light_status[light]["change_one"]:
            color_or_brightness: int = randrange(1, 3, 1)
            if color_or_brightness == 2:
                return {
                    "entity_id": light,
                    "transition": self.get_transition(),
                    "brightness": self.get_static_or_random(
                        self._light_status[light]["brightness"]
                    ),
                }

        if self._sequence:
            color: dict[str, Any] = self._colors[self._current_color_index]
        else:
            color = self.pick_color()

        attributes = {
            "entity_id": light,
            "transition": self.get_transition(),
        }
        if self._animate_color or initial:
            if CONF_COLOR_NEARBY_COLORS in color and color[CONF_COLOR_NEARBY_COLORS] > 0:
                attributes[color[CONF_COLOR_TYPE]] = self.find_nearby_color(color)
                _LOGGER.debug(
                    "Light %s: picked nearby %s color %s from base %s",
                    light,
                    color[CONF_COLOR_TYPE],
                    attributes[color[CONF_COLOR_TYPE]],
                    color[CONF_COLOR],
                )
            else:
                attributes[color[CONF_COLOR_TYPE]] = color[CONF_COLOR]
        if self._animate_brightness and CONF_BRIGHTNESS in color:
            attributes["brightness"] = self.get_static_or_random(color[CONF_BRIGHTNESS])
        elif self._animate_brightness and self._global_brightness is not None:
            attributes["brightness"] = self.get_static_or_random(self._global_brightness)
        elif isinstance(self._global_brightness, int):
            attributes["brightness"] = self._global_brightness
        elif isinstance(self._global_brightness, list):
            _LOGGER.warning("Global brightness is a list but animate_brightness is False, ignoring")

        if CONF_BRIGHTNESS in color and color[CONF_COLOR_ONE_CHANGE_PER_TICK]:
            self._light_status[light] = {
                "change_one": color[CONF_COLOR_ONE_CHANGE_PER_TICK],
                "brightness": color[CONF_BRIGHTNESS],
            }
        return attributes

    def _convert_to_rgb(self, color: dict[str, Any]) -> tuple[int, int, int] | None:
        """Determine a base RGB triple using Home Assistant color helpers.

        This helper converts the provided `color` configuration mapping into a
        canonical RGB triple (r, g, b) with integer components in the 0-255
        range which is suitable for perturbation in HLS space.

        Supported input color types (driven by `color[CONF_COLOR_TYPE]`):
        - ATTR_RGB_COLOR: expects (r, g, b) tuple of bytes.
        - ATTR_RGBW_COLOR: expects (r, g, b, w); converted via
          `color_rgbw_to_rgb`.
        - ATTR_RGBWW_COLOR: expects (r, g, b, cw, ww); converted via
          `color_rgbww_to_rgb` using `MIN_KELVIN`/`MAX_KELVIN` bounds.
        - ATTR_COLOR_TEMP_KELVIN: expects an integer kelvin; converted via
          `color_temperature_to_rgb` and scaled from 0..1 to 0..255.
        - ATTR_HS_COLOR: expects (h, s) and converted via `color_hs_to_RGB`.
        - ATTR_XY_COLOR: expects (x, y) and converted via `color_xy_to_RGB`.

        Returns:
            A tuple[int, int, int] with values in 0..255 on success, or
            `None` if conversion fails (invalid/malformed input). The caller
            should handle `None` (it will typically fall back to returning the
            original configured color).

        """

        ctype = color[CONF_COLOR_TYPE]
        if ctype == ATTR_RGB_COLOR:
            try:
                r, g, b = color[CONF_COLOR]
                return (int(r), int(g), int(b))
            except (TypeError, ValueError, IndexError):
                return None

        if ctype == ATTR_RGBW_COLOR:
            try:
                r, g, b, w = color[CONF_COLOR]
                return color_rgbw_to_rgb(r, g, b, w)
            except (TypeError, ValueError, IndexError):
                return None

        if ctype == ATTR_RGBWW_COLOR:
            try:
                # color[CONF_COLOR] is expected to be (r, g, b, cw, ww)
                r, g, b, cw, ww = color[CONF_COLOR]
                # Call with required min/max kelvin bounds.
                return color_rgbww_to_rgb(r, g, b, cw, ww, MIN_KELVIN, MAX_KELVIN)
            except (TypeError, ValueError, IndexError):
                return None

        if ctype == ATTR_COLOR_TEMP_KELVIN:
            try:
                kelvin = int(color[CONF_COLOR])
                # Convert color temperature (kelvin) to an RGB triple
                r_f, g_f, b_f = color_temperature_to_rgb(float(kelvin))
                return (
                    int(min(max(r_f * 255.0, 0), 255)),
                    int(min(max(g_f * 255.0, 0), 255)),
                    int(min(max(b_f * 255.0, 0), 255)),
                )
            except (TypeError, ValueError):
                return None

        if ctype == ATTR_HS_COLOR:
            try:
                h, s = color[CONF_COLOR]
                # Home Assistant helper expects HS -> RGB (0..360, 0..100)
                r, g, b = color_hs_to_RGB(float(h), float(s))
                return (int(r), int(g), int(b))
            except (TypeError, ValueError, IndexError):
                return None

        if ctype == ATTR_XY_COLOR:
            try:
                x, y = color[CONF_COLOR]
                r, g, b = color_xy_to_RGB(float(x), float(y))
                return (int(r), int(g), int(b))
            except (TypeError, ValueError, IndexError):
                return None

        return None

    def _convert_back_to_original_color_type(
        self, color: dict[str, Any], r: int, g: int, b: int
    ) -> Any:
        """Convert an RGB triple back to the original color representation.

        This helper takes the original `color` configuration mapping and an
        integer RGB triple (r, g, b) produced by perturbation. It returns a
        value matching the original color type expected by the caller:

        - For `ATTR_RGB_COLOR` returns a list [r, g, b].
        - For `ATTR_RGBW_COLOR` / `ATTR_RGBWW_COLOR` attempts to convert
          using Home Assistant helpers and preserves white-channel values
          from the original config if conversion fails.
        - For `ATTR_HS_COLOR` and `ATTR_XY_COLOR` returns HS/XY values
          derived from the RGB triple (rounded for readability).
        - For `ATTR_COLOR_TEMP_KELVIN` returns an integer kelvin via
          an approximate inverse search (may be approximate).

        On conversion failure the original configured color (if present)
        is returned; otherwise an empty list is returned.
        """
        ctype = color[CONF_COLOR_TYPE]
        if ctype == ATTR_RGB_COLOR:
            return [r, g, b]

        if ctype == ATTR_RGBW_COLOR:
            try:
                # color_rgb_to_rgbw expects r,g,b and returns (r,g,b,w)
                rgbw = color_rgb_to_rgbw(r, g, b)
                return list(rgbw)
            except (TypeError, ValueError):
                # Preserve original white channel if conversion fails
                try:
                    whites = list(color[CONF_COLOR][3:4])
                except (IndexError, TypeError, ValueError):
                    whites = []
                return [r, g, b, *whites]

        if ctype == ATTR_RGBWW_COLOR:
            try:
                # Call the helper with min/max kelvin bounds
                rgbww = color_rgb_to_rgbww(r, g, b, MIN_KELVIN, MAX_KELVIN)
                return list(rgbww)
            except (TypeError, ValueError):
                try:
                    whites = list(color[CONF_COLOR][3:5])
                except (IndexError, TypeError, ValueError):
                    whites = []
                return [r, g, b, *whites]

        if ctype == ATTR_HS_COLOR:
            try:
                h, s = color_RGB_to_hs(float(r), float(g), float(b))
                return [round(h, 1), round(s, 1)]
            except (IndexError, TypeError, ValueError):
                return [r, g, b]

        if ctype == ATTR_XY_COLOR:
            try:
                x, y = color_RGB_to_xy(int(r), int(g), int(b))
                return [round(x, 4), round(y, 4)]
            except (IndexError, TypeError, ValueError):
                return [r, g, b]

        if ctype == ATTR_COLOR_TEMP_KELVIN:
            try:
                kelvin = _rgb_to_kelvin((r, g, b))
                return int(kelvin)
            except (IndexError, TypeError, ValueError):
                return [r, g, b]
        return color.get(CONF_COLOR) if CONF_COLOR in color else []

    def find_nearby_color(self, color: dict[str, Any]) -> Any:
        """Return a color near the configured color by applying a small random perturbation.

        The method accepts a color configuration dictionary (as used by the animation
        configuration) and returns a perturbed color in the same representation as the
        input. Supported input types include ATTR_RGB_COLOR, ATTR_RGBW_COLOR,
        ATTR_RGBWW_COLOR, ATTR_COLOR_TEMP_KELVIN, ATTR_HS_COLOR and ATTR_XY_COLOR.
        For color-temperature and white-capable types the implementation converts to an
        RGB base, perturbs the color in HLS space, then converts back to the original
        representation. If the color type is unsupported the original color is returned
        unchanged.

        Args:
            color: Mapping containing at least CONF_COLOR and CONF_COLOR_TYPE and
                   optionally CONF_COLOR_NEARBY_COLORS which controls perturbation amount.

        Returns:
            A perturbed color in the same format as the provided color (list for RGB/HS/XY,
            int for color temperature), or the original color if the type is unsupported.

        """
        # Raw configured color value (may be list/tuple or a single int).
        raw = color.get(CONF_COLOR) if CONF_COLOR in color else []

        modifier = color[CONF_COLOR_NEARBY_COLORS]
        ctype = color[CONF_COLOR_TYPE]
        if ctype not in {
            ATTR_RGB_COLOR,
            ATTR_RGBW_COLOR,
            ATTR_RGBWW_COLOR,
            ATTR_COLOR_TEMP_KELVIN,
            ATTR_HS_COLOR,
            ATTR_XY_COLOR,
        }:
            # Unsupported color types: return the configured color as-is
            return raw if raw else []

        base_rgb = self._convert_to_rgb(color=color)

        if base_rgb is None:
            return raw if raw else []

        # colorsys expects RGB values in the 0..1 range. Our stored
        # colors are bytes (0..255), so normalize first.
        r_n, g_n, b_n = (c / 255.0 for c in base_rgb)
        hue, light, sat = colorsys.rgb_to_hls(r_n, g_n, b_n)

        # Scale the modifier to a 0..1 range. The configured `modifier`
        # is a small integer (1-10); dividing by 100 produces a
        # reasonable perturbation amount for H/L/S channels.
        delta = modifier / 100.0
        hmod = uniform(hue - delta, hue + delta)
        lmod = uniform(light - delta, light + delta)
        smod = uniform(sat - delta, sat + delta)

        # Clamp perturbed H/L/S into valid 0..1 ranges before converting
        # back to RGB to avoid surprising results.
        # Hue is cyclic; wrap-around using modulo so small perturbations near
        # the 0/1 boundary remain adjacent rather than being clamped far away.
        hmod = hmod % 1.0
        lmod = min(max(lmod, 0.0), 1.0)
        smod = min(max(smod, 0.0), 1.0)

        # Convert back to RGB (0..1), scale to 0..255 and clamp to byte
        # range, returning integers.
        r_f, g_f, b_f = colorsys.hls_to_rgb(hmod, lmod, smod)
        r = int(min(max(r_f * 255.0, 0), 255))
        g = int(min(max(g_f * 255.0, 0), 255))
        b = int(min(max(b_f * 255.0, 0), 255))

        return self._convert_back_to_original_color_type(color=color, r=r, g=g, b=b)

    def get_active_lights(self) -> list[str]:
        """Return the list of active lights for this animation."""
        return self._active_lights

    def get_change_amount(self) -> float:
        """Return the change amount (possibly randomized).

        The configured change amount may be a fixed number a two-item
        range or 'all'; this helper returns a concrete numeric value.
        """
        if isinstance(self._change_amount, str):
            if self._change_amount == "all":
                return len(self._active_lights)
            return 0
        return self.get_static_or_random(self._change_amount)

    def get_change_frequency(self) -> float:
        """Return the change frequency (possibly randomized)."""
        return self.get_static_or_random(self._change_frequency)

    def get_transition(self) -> float:
        """Return the transition time to use for light updates."""
        return self.get_static_or_random(self._transition)

    def get_static_or_random(self, value: int | list, step: int = 1) -> float:
        """Return a concrete value from either a static or range value.

        If `value` is a list it will be treated as a two-element range and
        a random value within the range will be returned. If either bound
        is a float the result will be a rounded float, otherwise an int
        step-based random integer is returned.

        Args:
            value: Either a single value or a two-item sequence representing
                a range [min, max].
            step: Step size used when picking an integer in the range.

        Returns:
            A concrete numeric value (int or float).

        """
        if isinstance(value, list):
            if isinstance(value[0], float) or isinstance(value[1], float):
                # Use math.nextafter to nudge the upper bound slightly upward so
                # that after rounding the result can inclusively reach the
                # configured upper value. This makes the behavior effectively
                # inclusive for the rounded one-decimal result.
                upper = math.nextafter(value[1], math.inf)
                return round(uniform(value[0], upper), 1)
            # randrange's stop is exclusive. Add `step` to the stop value so
            # the configured upper bound can be selected when it aligns with
            # the step. This makes the integer range behave inclusively.
            return randrange(value[0], value[1] + step, step)
        return value

    def pick_color(self) -> dict[str, Any]:
        """Pick a color group according to configured weights."""
        color: list = choices(self._colors, self._weights, k=1)
        return color.pop()

    def pick_lights(self, change_amount: int) -> list[str]:
        """Return a list of lights to change this tick.

        If `ignore_off` is enabled the method filters out lights that are
        currently off when selecting a random subset.
        """
        if not self._ignore_off:
            to_change: list = []
            randomized_list: list = sample(self._active_lights, k=change_amount)
            for light in randomized_list:
                state = self._hass.states.get(light)
                if state.state != "off":
                    to_change.append(light)
                if len(to_change) >= change_amount:
                    return to_change
            return to_change
        return sample(self._active_lights, k=change_amount)

    async def release(self) -> None:
        """Release ownership of all lights and stop the animation.

        Restores any stored states as necessary and notifies Home
        Assistant that the animation stopped.
        """
        for light in self._active_lights:
            if Animations.instance:
                await Animations.instance.release_light(self, light)
        if Animations.instance:
            Animations.instance.release_animation(self)
        self._hass.bus.fire(
            EVENT_NAME_CHANGE,
            {"animation": self._name, "state": EVENT_STATE_STOPPED},
        )

    def remove_light(self, light: str) -> None:
        """Remove a light from this animation's active list."""
        if light in self._active_lights:
            self._active_lights.remove(light)

    async def update_light(self, entity_id: str, initial: bool = False) -> None:
        """Update a single light if this animation owns it.

        Args:
            entity_id: The light entity id to update.
            initial: If True, indicate this is the initial update.

        Returns:
            None

        """
        if Animations.instance and Animations.instance.get_animation_for_light(entity_id) != self:
            return _LOGGER.info(
                "Skipping light %s due to conflicting animation with higher priority, %s",
                entity_id,
                self._name,
            )
        await safe_call(
            self._hass,
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            self.build_light_attributes(entity_id, initial),
        )
        return None

    async def update_lights(self) -> None:
        """Select lights to update this tick and apply updates concurrently."""
        if isinstance(self._change_amount, str):
            if self._change_amount == "all":
                change_amount: float = len(self._active_lights)
            else:
                return
        else:
            change_amount = self.get_static_or_random(self._change_amount)
            if change_amount <= 0:
                return

        lights_to_change: list = self.pick_lights(int(change_amount))
        if self._sequence:
            self._current_color_index += 1
        if self._current_color_index >= len(self._colors):
            self._current_color_index = 0

        updates: list = [self.update_light(light) for light in lights_to_change]
        await asyncio.gather(*updates)

    async def start(self) -> None:
        """Perform initial updates and start the animation loop task.

        If no change frequency is configured the animation will release
        immediately after the initial update.
        """
        updates: list = [self.update_light(light, True) for light in self._active_lights]
        await asyncio.gather(*updates)
        if not self._change_frequency:
            await self.release()
            return
        if not self._task:
            self._task = asyncio.get_event_loop().create_task(self.animate())
            self._hass.bus.fire(
                EVENT_NAME_CHANGE,
                {"animation": self._name, "state": EVENT_STATE_STARTED},
            )

    async def stop(self) -> None:
        """Cancel the animation task and wait for it to finish."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                _LOGGER.info("Animation '%s' has been cancelled", self._name)


class Animations:
    """Manager for all running animations in the system.

    This singleton-like class keeps track of running animations, stored
    previous light states, and ownership of lights when multiple
    animations request the same entity.
    """

    instance: Animations | None = None

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the animations manager with empty state."""
        self.animations: dict[str, Animation] = {}
        self.states: dict[str, Any] = {}
        self._external_light_listener: Callable[[], None] | None = None
        self._light_animations: dict[str, list[Animation]] = {}
        self.light_owner: dict[str, Animation] = {}
        self._conflicted_lights: dict[str, Any] = {}
        self.hass: HomeAssistant = hass

    def build_attributes_from_state(self, state: State) -> dict[str, Any]:
        """Build a service data mapping to restore a previously stored state.

        Args:
            state: A Home Assistant state object for the light.

        Returns:
            A mapping of attributes appropriate for a light.turn_on service
            that will approximate the provided state.

        """
        attributes: dict[str, Any] = {
            "entity_id": state.entity_id,
            "brightness": state.attributes.get("brightness"),
            "transition": 1,
        }
        if ATTR_COLOR_MODE in state.attributes:
            if state.attributes[ATTR_COLOR_MODE] == ColorMode.XY:
                attributes[ATTR_XY_COLOR] = state.attributes.get(ATTR_XY_COLOR)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.COLOR_TEMP:
                attributes[ATTR_COLOR_TEMP] = state.attributes.get(ATTR_COLOR_TEMP)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.HS:
                attributes[ATTR_HS_COLOR] = state.attributes.get(ATTR_HS_COLOR)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.RGB:
                attributes[ATTR_RGB_COLOR] = state.attributes.get(ATTR_RGB_COLOR)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.RGBW:
                attributes[ATTR_RGBW_COLOR] = state.attributes.get(ATTR_RGBW_COLOR)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.RGBWW:
                attributes[ATTR_RGBWW_COLOR] = state.attributes.get(ATTR_RGBWW_COLOR)
            elif state.attributes[ATTR_COLOR_MODE] == ColorMode.WHITE:
                attributes[ATTR_COLOR_MODE] = ColorMode.WHITE
        else:
            exclusive_properties: list = [
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

    def external_light_change(self, event: Event[EventStateChangedData]) -> Any:
        """Sync wrapper that schedules the async external change handler.

        The state change tracker expects a synchronous callable. Schedule
        the actual async handler as a task so it can run in the event loop.
        """
        # Schedule the async handler and return immediately
        try:
            asyncio.run_coroutine_threadsafe(
                self._handle_external_light_change(event), self.hass.loop
            )
        except RuntimeError:
            # Fall back to calling async_create_task if we're already in the loop.
            self.hass.async_create_task(self._handle_external_light_change(event))

    async def _handle_external_light_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle external state changes for tracked lights (async).

        When a light that was previously off is turned on externally this
        listener attempts to re-apply the animation for the light if an
        animation is responsible for it.
        """
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not (new_state and old_state):
            return
        if new_state.state == "on" and old_state.state == "off":
            if entity_id not in self.states:
                self.states[entity_id] = self.hass.states.get(entity_id)
            animation = self.refresh_animation_for_light(entity_id)
            if animation:
                await animation.update_light(entity_id)

    def get_animation_by_priority(self, priority: int) -> Animation | None:
        """Return an animation with the given priority, if any."""
        for animation in self.animations.values():
            if animation.priority == priority:
                return animation
        return None

    def get_animation_for_light(self, entity_id: str) -> Animation:
        """Return the animation that currently owns the given light."""
        return self.light_owner[entity_id]

    def refresh_animation_for_light(self, entity_id: str) -> Animation | None:
        """Pick the highest-priority animation that targets the given light."""
        selected: Animation | None = None
        selected_priority: int = -(2**31)
        for animation in self._light_animations[entity_id]:
            if entity_id in animation.lights and animation.priority > selected_priority:
                selected = animation
                selected_priority = animation.priority
        return selected

    async def start(self, data: dict[str, Any]) -> None:
        """Validate input and start a new animation from service data."""
        config = self.validate_start(data)
        id_name: str = data[CONF_NAME]
        if id_name in self.animations:
            _LOGGER.info("Animation '%s' was already running, so stopping it", id_name)
            await self.animations[id_name].stop()
        _LOGGER.info("Starting animation '%s'", id_name)
        animation = Animation(self.hass, config)
        for light in animation.lights:
            if (
                light not in self.light_owner
                or self.get_animation_for_light(light).priority <= animation.priority
            ):
                self.light_owner[light] = animation
            if light not in self._light_animations:
                self._light_animations[light] = []
            self._light_animations[light].append(animation)
        self.animations[id_name] = animation
        await animation.start()

    async def stop(self, data: dict[str, Any]) -> None:
        """Stop a running animation identified by service data."""
        config = self.validate_stop(data)
        id_name: str = config[CONF_NAME]
        _LOGGER.info("Stopping animation '%s'", id_name)
        if id_name in self.animations:
            await self.animations[id_name].stop()

    def refresh_listener(self) -> None:
        """Refresh the external state change listener used to track lights.

        The listener is registered when there are stored states and
        unregistered when the stored-states map becomes empty.
        """
        if self._external_light_listener is not None:
            try:
                self._external_light_listener()
            except ValueError as e:
                _LOGGER.info(
                    "Unable to remove external_light_listener. %s: %s",
                    type(e).__name__,
                    e,
                )
            self._external_light_listener = None
        if len(self.states) > 0:
            self._external_light_listener = async_track_state_change_event(
                self.hass, self.states.keys(), self.external_light_change
            )

    def release_animation(self, animation: Animation) -> None:
        """Remove an animation from the active map and refresh listeners."""
        del self.animations[animation.name]
        self.refresh_listener()

    async def release_light(
        self,
        animation: Animation,
        entity_id: str,
        skip_ownership: bool = False,
        skip_restore: bool = False,
    ) -> None:
        """Release ownership of a light for a given animation.

        This handles handing ownership to another animation, restoring
        the previous state, and cleaning up stored state.
        """
        self._light_animations[entity_id].remove(animation)
        if self.light_owner[entity_id] != animation:
            return _LOGGER.info(
                "Not releasing light %s as it is owned by another animation %s",
                entity_id,
                self.light_owner[entity_id].name,
            )
        if len(self._light_animations[entity_id]) > 0 and not skip_ownership:
            light_owner = self.refresh_animation_for_light(entity_id)
            if light_owner:
                self.light_owner[entity_id] = light_owner
                return _LOGGER.info(
                    "Changing owner from %s to %s",
                    animation.name,
                    self.light_owner[entity_id].name,
                )
        if animation.restore and not skip_restore:
            previous_state = self.states[entity_id]
            if previous_state.state == "on":
                await safe_call(
                    self.hass,
                    LIGHT_DOMAIN,
                    SERVICE_TURN_ON,
                    self.build_attributes_from_state(previous_state),
                )
            elif animation.restore_power:
                await safe_call(self.hass, LIGHT_DOMAIN, SERVICE_TURN_OFF, {"entity_id": entity_id})
        del self.states[entity_id]
        return None

    async def add_lights_to_animation(self, data: dict[str, Any]) -> None:
        """Service handler to add lights to an already running animation.

        The service accepts either the animation name or a switch entity to
        identify the target animation and will raise IntegrationError if
        the target animation does not exist or input is invalid.
        """
        config = ADD_LIGHTS_TO_ANIMATION_SERVICE_SCHEMA(dict(data))
        lights: list = config.get(CONF_LIGHTS)
        if (
            config.get(CONF_NAME, None) is not None
            and config.get(CONF_ANIMATED_SCENE_SWITCH, None) is not None
        ) or (
            config.get(CONF_NAME, None) is None
            and config.get(CONF_ANIMATED_SCENE_SWITCH, None) is None
        ):
            _LOGGER.error(
                "Animated Scene Name or Animated Scene Switch must be listed but not both"
            )
            raise IntegrationError(
                "Animated Scene Name or Animated Scene Switch must be listed but not both"
            )
        if config.get(CONF_NAME, None) is not None:
            name: str = config.get(CONF_NAME)
        else:
            name = self.hass.states.get(config.get(CONF_ANIMATED_SCENE_SWITCH)).attributes.get(
                ATTR_FRIENDLY_NAME, config.get(CONF_ANIMATED_SCENE_SWITCH)
            )

        if name not in self.animations:
            _LOGGER.error("Tried to add a light to an animation that doesn't exist")
            raise IntegrationError(f"Animation {name} is not running")

        animation: Animation = self.animations[name]

        for light in lights:
            if (
                light not in self.light_owner
                or self.get_animation_for_light(light).priority <= animation.priority
            ):
                self.light_owner[light] = animation
            if light not in self._light_animations:
                self._light_animations[light] = []
            self._light_animations[light].append(animation)

        animation.add_lights(lights)

    async def remove_lights(self, data: dict[str, Any]) -> None:
        """Service handler to remove lights from animations and optionally restore."""
        config = REMOVE_LIGHTS_SERVICE_SCHEMA(dict(data))
        lights: list = config.get(CONF_LIGHTS)
        skip_restore: bool = config.get(CONF_SKIP_RESTORE)
        affected_animations: set[Animation] = set()
        updates: list = []
        for light in lights:
            if light in self.light_owner:
                animation: Animation = self.light_owner[light]
                _LOGGER.info("Releasing light '%s' from animation '%s'", light, animation.name)
                affected_animations.add(animation)
                animation.remove_light(light)
                updates.append(self.release_light(animation, light, True, skip_restore))

        await asyncio.gather(*updates)
        for light in lights:
            if light in self._light_animations and not self._light_animations[light]:
                del self._light_animations[light]
        for animation in affected_animations:
            if len(animation.get_active_lights()) == 0:
                await animation.stop()

    def store_state(self, light: str) -> None:
        """Store the current state of a light for later restoration."""
        if light not in self.states:
            self.states[light] = self.hass.states.get(light)

    def store_states(self, lights: list) -> None:
        """Store the states for multiple lights and refresh the listener."""
        for light in lights:
            self.store_state(light)
        self.refresh_listener()

    def validate_start(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate start service data against the START_SERVICE_SCHEMA.

        Raises IntegrationError if validation fails.
        """
        try:
            config = START_SERVICE_SCHEMA(dict(data))
        except vol.Invalid as err:
            _LOGGER.exception("Error with received configuration")
            raise IntegrationError("Service data did not match schema") from err
        return config

    def validate_stop(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate stop service data against the STOP_SERVICE_SCHEMA.

        Raises IntegrationError if validation fails.
        """
        try:
            config = STOP_SERVICE_SCHEMA(dict(data))
        except vol.Invalid as err:
            _LOGGER.exception("Error with received configuration")
            raise IntegrationError("Service data did not match schema") from err
        return config
