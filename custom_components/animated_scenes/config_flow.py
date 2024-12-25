"""Config flow for the Animated Scenes integration.

This module implements the config and options flows used by Home
Assistant to configure Animated Scenes. It includes small helper
functions used to parse and validate user input from the UI.
"""

import copy
import logging
from numbers import Number
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_BRIGHTNESS, CONF_ICON, CONF_LIGHTS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv
from homeassistant.util import uuid

from .const import (
    ABORT_ACTIVITY_SENSOR_NO_OPTIONS,
    ABORT_INTEGRATION_NO_OPTIONS,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CHANGE_AMOUNT_MAX,
    CHANGE_AMOUNT_MIN,
    CHANGE_FREQUENCY_MAX,
    CHANGE_FREQUENCY_MIN,
    COLOR_SELECTOR_RGB_UI,
    COLOR_SELECTOR_YAML,
    COMPONENT_COLOR_CONFIG_URL,
    CONF_ANIMATE_BRIGHTNESS,
    CONF_ANIMATE_COLOR,
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_CHANGE_SEQUENCE,
    CONF_COLOR,
    CONF_COLOR_ADD_COLOR,
    CONF_COLOR_DELETE_COLOR,
    CONF_COLOR_NEARBY_COLORS,
    CONF_COLOR_ONE_CHANGE_PER_TICK,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_COLOR_WEIGHT,
    CONF_COLORS,
    CONF_ENTITY_TYPE,
    CONF_IGNORE_OFF,
    CONF_PRIORITY,
    CONF_RESTORE,
    CONF_RESTORE_POWER,
    CONF_TRANSITION,
    DEFAULT_ANIMATE_BRIGHTNESS,
    DEFAULT_ANIMATE_COLOR,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CHANGE_AMOUNT,
    DEFAULT_CHANGE_FREQUENCY,
    DEFAULT_CHANGE_SEQUENCE,
    DEFAULT_COLOR_ADD_COLOR,
    DEFAULT_COLOR_DELETE_COLOR,
    DEFAULT_COLOR_NEARBY_COLORS,
    DEFAULT_COLOR_ONE_CHANGE_PER_TICK,
    DEFAULT_COLOR_WEIGHT,
    DEFAULT_ICON,
    DEFAULT_IGNORE_OFF,
    DEFAULT_PRIORITY,
    DEFAULT_RESTORE,
    DEFAULT_RESTORE_POWER,
    DEFAULT_TRANSITION,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    ENTITY_SCENE,
    ERROR_BRIGHTNESS_NOT_INT_OR_RANGE,
    ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL,
    ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE,
    ERROR_COLORS_IS_BLANK,
    ERROR_COLORS_MALFORMED,
    ERROR_TRANSITION_NOT_INT_OR_RANGE,
    TRANSITION_MAX,
    TRANSITION_MIN,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)

COLOR_SELECTOR_OPTION_LIST = [
    selector.SelectOptionDict(label="Use RGB Selectors", value=COLOR_SELECTOR_RGB_UI),
    selector.SelectOptionDict(label="Configure via YAML", value=COLOR_SELECTOR_YAML),
]


def _if_list_or_int_to_str(invar: Any) -> Any:
    """Return a string representation for an int or a 2-item list.

    If ``invar`` is a list it is converted to a bracketed comma-separated
    string. If it represents an integer (or numeric string) the string
    form of the integer is returned. Other values are returned
    unchanged.
    """
    # _LOGGER.debug(f"[if_list_or_int_to_str] starting input: {invar}, type: {type(invar)}")
    if isinstance(invar, list):
        strlist: str = "[" + ", ".join(str(n) for n in invar) + "]"
        # _LOGGER.debug(f"[if_list_or_int_to_str] input: {invar}, strlist: {strlist}")
        return strlist
    is_int_check, is_int_value = _is_int(invar)
    if is_int_check:
        # _LOGGER.debug(f"[if_list_or_int_to_str] input: {invar}, strint: {str(is_int_value)}")
        return str(is_int_value)
    # _LOGGER.debug(f"[if_list_or_int_to_str] input: {invar}, type: {type(invar)}")
    return invar


def _strlist_to_list(invar: str) -> list[str]:
    """Convert a bracketed comma-separated string to a two-item list.

    Example: the string "[1, 2]" becomes ["1", " 2"]. This helper
    does not coerce element types.
    """
    return invar.strip("][").split(",")


def _is_int(invar: Any) -> tuple[bool, Any]:
    """Return (True, int) if value can be interpreted as an integer.

    Accepts numeric types and numeric strings. If the input is an
    integer-like numeric value the returned tuple is (True, int(value)).
    Otherwise (False, original_value) is returned.
    """
    # _LOGGER.debug(f"[is_int] starting input: {invar}, type: {type(invar)}")
    if invar is None or not isinstance(invar, Number | str):
        return False, invar
    try:
        value = float(invar)
    except (TypeError, ValueError):
        return False, invar
    if value.is_integer():
        return True, int(value)
    return False, invar


def _is_int_or_list(
    invar: Any, minvar: int | None = None, maxvar: int | None = None
) -> tuple[bool, Any]:
    """Validate an input as either an int or a two-item int list.

    Returns (True, coerced_value) on success where coerced_value is an
    int or a normalized two-item list. Returns (False, original) on
    failure.
    """
    # _LOGGER.debug(f"[is_int_or_list] starting input: {invar}, type: {type(invar)}")
    if invar is None:
        # _LOGGER.debug(f"[is_int_or_list] input is None: {invar} (True)")
        return True, invar
    is_int_check, is_int_value = _is_int(invar)
    if is_int_check:
        if (minvar is None or is_int_value >= minvar) and (
            maxvar is None or is_int_value <= maxvar
        ):
            # _LOGGER.debug(f"[is_int_or_list] input is int in range: {invar} [{minvar}, {maxvar}] (True)")
            return True, is_int_value
        # _LOGGER.debug(f"[is_int_or_list] input is int but NOT in range: {invar} [{minvar}, {maxvar}] (False)")
        return False, invar
    if isinstance(invar, str):
        invar = invar.strip()
        if invar.startswith("[") and invar.endswith("]") and invar.count(",") == 1:
            # _LOGGER.debug(f"[is_int_or_list] input is a 2 item string list, converting to list: {invar}")
            invar = _strlist_to_list(invar)
        else:
            # _LOGGER.debug(f"[is_int_or_list] input is a string but is not a 2 item list: {invar} (False)")
            return False, invar

    if isinstance(invar, list):
        if len(invar) == 2:
            is_int0_check, is_int0_value = _is_int(invar[0])
            is_int1_check, is_int1_value = _is_int(invar[1])
            if not (is_int0_check and is_int1_check):
                # _LOGGER.debug(f"[is_int_or_list] input is a 2 item list, but 2 items aren't integers: {invar} (False)")
                return False, invar
            if is_int0_value > is_int1_value:
                invar = [is_int1_value, is_int0_value]
            else:
                invar = [is_int0_value, is_int1_value]
            if (minvar is None or (invar[0] >= minvar and invar[1] >= minvar)) and (
                maxvar is None or (invar[0] <= maxvar and invar[1] <= maxvar)
            ):
                if invar[0] == invar[1]:
                    # _LOGGER.debug(f"[is_int_or_list] input is int in range: {invar} [{minvar}, {maxvar}] (True)")
                    return True, invar[0]
                # _LOGGER.debug(f"[is_int_or_list] input is a 2 int list within min, max: {invar} [{minvar}, {maxvar}] (True)")
                return True, invar
            # _LOGGER.debug(f"[is_int_or_list] input is a 2 item list, but not within min, max: {invar} [{minvar}, {maxvar}] (False)")
            return False, invar
        # _LOGGER.debug(f"[is_int_or_list] input is a list, but doesn't have 2 items: {invar} (False)")
        return False, invar
    # _LOGGER.debug(f"[is_int_or_list] input does not meet any criteria: {invar}, type: {type(invar)} (False)")
    return False, invar


def _is_int_list_or_all(
    invar: Any, minvar: int | None = None, maxvar: int | None = None
) -> tuple[bool, Any]:
    """Validate input as an int/list or the literal 'all'.

    Accepts None, integers, two-item integer lists, or the string
    "all". Returns (True, coerced_value) when input is acceptable.
    """
    # _LOGGER.debug(f"[is_int_list_or_all] starting input: {invar}, type: {type(invar)}")
    if invar is None:
        # _LOGGER.debug(f"[is_int_list_or_all] input is None: {invar} (True)")
        return True, invar
    is_int_or_list_check, is_int_or_list_value = _is_int_or_list(invar, minvar, maxvar)
    if is_int_or_list_check:
        # _LOGGER.debug(f"[is_int_list_or_all] input is valid int or list: {is_int_or_list_value} (True)")
        return True, is_int_or_list_value
    if isinstance(invar, str):
        invar = invar.strip()
    if invar == "all":
        # _LOGGER.debug(f"[is_int_list_or_all] input is 'all': {invar} (True)")
        return True, invar
    # _LOGGER.debug(f"[is_int_list_or_all] input does not meet any criteria: {invar}, type: {type(invar)} (False)")
    return False, invar


def _overrride_max_change_amount(invar: Any, light_count: int) -> Any:
    """Adjust change-amount values to account for the available lights.

    If a fixed integer exceeds the number of available lights, returns
    the string "all". If a two-item range exceeds the number of lights,
    the upper bound will be clamped.
    """
    _LOGGER.debug("[overrride_max_change_amount] input: %s, light_count: %s", invar, light_count)
    if isinstance(invar, int) and invar > light_count:
        # _LOGGER.debug("[overrride_max_change_amount] return: 'all'")
        return "all"
    if isinstance(invar, list) and invar[1] > light_count:
        if invar[0] >= light_count:
            # _LOGGER.debug("[overrride_max_change_amount] return: 'all'")
            return "all"
        invar[1] = light_count
    # _LOGGER.debug(f"[overrride_max_change_amount] return: {invar}")
    return invar


def _clean_color_rgb_dict(color_rgb_dict: dict) -> dict:
    """Remove UI-only helper keys from the RGB color dictionary.

    The UI keeps temporary keys such as add/delete flags in the color
    dict; this function removes those keys before the structure is
    persisted to the integration configuration.
    """
    _LOGGER.debug("[clean_color_rgb_dict] initial color_rgb_dict: %s", color_rgb_dict)
    for key, color in copy.deepcopy(color_rgb_dict).items():
        color_rgb_dict[key].pop(CONF_COLOR_ADD_COLOR, None)
        if color.get(CONF_COLOR_DELETE_COLOR, False):
            color_rgb_dict.pop(key, None)
        else:
            color_rgb_dict[key].pop(CONF_COLOR_DELETE_COLOR, None)
    _LOGGER.debug("[clean_color_rgb_dict] final color_rgb_dict: %s", color_rgb_dict)
    return color_rgb_dict


async def _async_build_schema(
    user_input: dict[str, Any] | None,
    default_dict: dict[str, Any],
    options_flow: bool = False,
) -> vol.Schema:
    """Build a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> Any:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    build_schema = vol.Schema({})
    if not options_flow:
        build_schema = build_schema.extend(
            {
                vol.Required(
                    CONF_NAME,
                    default=_get_default(CONF_NAME),
                ): selector.TextSelector(selector.TextSelectorConfig()),
                vol.Optional(
                    CONF_ICON, default=_get_default(CONF_ICON, DEFAULT_ICON)
                ): selector.IconSelector(selector.IconSelectorConfig()),
            }
        )
    return build_schema.extend(
        {
            vol.Optional(
                CONF_PRIORITY, default=_get_default(CONF_PRIORITY, DEFAULT_PRIORITY)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-100,
                    max=100,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_CHANGE_FREQUENCY,
                default=_if_list_or_int_to_str(
                    _get_default(CONF_CHANGE_FREQUENCY, DEFAULT_CHANGE_FREQUENCY)
                ),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_TRANSITION,
                default=_if_list_or_int_to_str(_get_default(CONF_TRANSITION, DEFAULT_TRANSITION)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_CHANGE_AMOUNT,
                default=_if_list_or_int_to_str(
                    _get_default(CONF_CHANGE_AMOUNT, DEFAULT_CHANGE_AMOUNT)
                ),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_BRIGHTNESS,
                default=_if_list_or_int_to_str(_get_default(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_CHANGE_SEQUENCE,
                default=_get_default(CONF_CHANGE_SEQUENCE, DEFAULT_CHANGE_SEQUENCE),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_ANIMATE_BRIGHTNESS,
                default=_get_default(CONF_ANIMATE_BRIGHTNESS, DEFAULT_ANIMATE_BRIGHTNESS),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_ANIMATE_COLOR,
                default=_get_default(CONF_ANIMATE_COLOR, DEFAULT_ANIMATE_COLOR),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_IGNORE_OFF,
                default=_get_default(CONF_IGNORE_OFF, DEFAULT_IGNORE_OFF),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_RESTORE, default=_get_default(CONF_RESTORE, DEFAULT_RESTORE)
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_RESTORE_POWER,
                default=_get_default(CONF_RESTORE_POWER, DEFAULT_RESTORE_POWER),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Required(CONF_LIGHTS, default=_get_default(CONF_LIGHTS)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True),
            ),
            vol.Required(
                CONF_COLOR_SELECTOR_MODE, default=_get_default(CONF_COLOR_SELECTOR_MODE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=COLOR_SELECTOR_OPTION_LIST,
                    multiple=False,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
    )


async def _async_build_color_yaml_schema(
    user_input: dict[str, Any] | None, default_dict: dict[str, Any]
) -> vol.Schema:
    """Build a color YAML schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> Any:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    build_schema = vol.Schema({})

    if _get_default(CONF_COLORS) is None or _get_default(CONF_COLORS) == {}:
        build_schema = build_schema.extend(
            {
                vol.Required(CONF_COLORS): selector.ObjectSelector(),
            }
        )
    else:
        build_schema = build_schema.extend(
            {
                vol.Required(
                    CONF_COLORS, default=_get_default(CONF_COLORS)
                ): selector.ObjectSelector(),
            }
        )

    return build_schema


async def _async_build_color_rgb_ui_schema(
    user_input: dict[str, Any] | None,
    default_dict: dict[str, Any],
    options_flow: bool = False,
    is_last_color: bool = False,
) -> vol.Schema:
    """Build a color RGB UI schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> Any:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    build_schema = vol.Schema(
        {
            vol.Optional(CONF_COLOR, default=_get_default(CONF_COLOR)): selector.ColorRGBSelector(
                selector.ColorRGBSelectorConfig()
            ),
            vol.Optional(
                CONF_BRIGHTNESS,
                default=_if_list_or_int_to_str(_get_default(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_COLOR_WEIGHT,
                default=_get_default(CONF_COLOR_WEIGHT, DEFAULT_COLOR_WEIGHT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=255,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_COLOR_ONE_CHANGE_PER_TICK,
                default=_get_default(
                    CONF_COLOR_ONE_CHANGE_PER_TICK, DEFAULT_COLOR_ONE_CHANGE_PER_TICK
                ),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_COLOR_NEARBY_COLORS,
                default=_get_default(CONF_COLOR_NEARBY_COLORS, DEFAULT_COLOR_NEARBY_COLORS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=10,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )
    if not options_flow or is_last_color:
        build_schema = build_schema.extend(
            {
                vol.Optional(
                    CONF_COLOR_ADD_COLOR,
                    default=_get_default(CONF_COLOR_ADD_COLOR, DEFAULT_COLOR_ADD_COLOR),
                ): cv.boolean,
            }
        )

    if options_flow:
        build_schema = build_schema.extend(
            {
                vol.Required(
                    CONF_COLOR_DELETE_COLOR,
                    default=_get_default(CONF_COLOR_DELETE_COLOR, DEFAULT_COLOR_DELETE_COLOR),
                ): cv.boolean,
            }
        )

    return build_schema


class AnimatedScenesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Animated Scenes.

    This class implements the steps shown to the user when creating an
    instance of the integration via the UI or importing YAML.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._data[CONF_COLOR_RGB_DICT] = {}
        self._data[CONF_COLORS] = {}
        self._errors: dict[str, Any] = {}
        self._entry = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step.

        Presents a menu to choose between creating an activity sensor or
        a scene entry, depending on whether an activity sensor already
        exists.
        """
        activity_sensor_exists = False
        if DOMAIN in self.hass.data:
            for entity in self.hass.data[DOMAIN].values():
                if entity.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_ACTIVITY_SENSOR:
                    activity_sensor_exists = True
                    break
        if activity_sensor_exists:
            return await self.async_step_scene(user_input=user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=["activity_sensor", "scene"],
        )

    async def async_step_activity_sensor(self, _: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create an activity sensor config entry immediately."""
        self._data.update({CONF_NAME: "Activity Sensor", CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR})
        # _LOGGER.debug(f"[async_step_activity_sensor] self._data: {self._data}")
        return self.async_create_entry(title="Activity Sensor", data=self._data)

    async def async_step_scene(
        self, user_input: dict[str, Any] | None = None, yaml_import: bool = False
    ) -> ConfigFlowResult:
        """Handle the scene creation step.

        Validates and normalizes user input before continuing to color
        configuration steps or creating the config entry.
        """

        self._errors = {}

        # Defaults
        defaults = {
            CONF_ICON: DEFAULT_ICON,
            CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
            CONF_ANIMATE_BRIGHTNESS: DEFAULT_ANIMATE_BRIGHTNESS,
            CONF_ANIMATE_COLOR: DEFAULT_ANIMATE_COLOR,
            CONF_CHANGE_AMOUNT: DEFAULT_CHANGE_AMOUNT,
            CONF_CHANGE_FREQUENCY: DEFAULT_CHANGE_FREQUENCY,
            CONF_CHANGE_SEQUENCE: DEFAULT_CHANGE_SEQUENCE,
            CONF_RESTORE: DEFAULT_RESTORE,
            CONF_RESTORE_POWER: DEFAULT_RESTORE_POWER,
            CONF_IGNORE_OFF: DEFAULT_IGNORE_OFF,
            CONF_TRANSITION: DEFAULT_TRANSITION,
            CONF_PRIORITY: DEFAULT_PRIORITY,
        }

        if user_input is not None:
            self._data.update(user_input)
            self._data.update({CONF_ENTITY_TYPE: ENTITY_SCENE})
            _LOGGER.debug(
                "Checking Change Amount: %s, type: %s",
                self._data.get(CONF_CHANGE_AMOUNT),
                type(self._data.get(CONF_CHANGE_AMOUNT)),
            )
            change_amount_check, change_amount_value = _is_int_list_or_all(
                self._data.get(CONF_CHANGE_AMOUNT),
                CHANGE_AMOUNT_MIN,
                CHANGE_AMOUNT_MAX,
            )
            if change_amount_check:
                self._data.update({CONF_CHANGE_AMOUNT: change_amount_value})
            else:
                self._errors["base"] = ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL
            _LOGGER.debug(
                "Checking Transition: %s, type: %s",
                self._data.get(CONF_TRANSITION),
                type(self._data.get(CONF_TRANSITION)),
            )
            transition_check, transition_value = _is_int_or_list(
                self._data.get(CONF_TRANSITION),
                TRANSITION_MIN,
                TRANSITION_MAX,
            )
            if transition_check:
                self._data.update({CONF_TRANSITION: transition_value})
            else:
                self._errors["base"] = ERROR_TRANSITION_NOT_INT_OR_RANGE
            _LOGGER.debug(
                "Checking Change Frequency: %s, type: %s",
                self._data.get(CONF_CHANGE_FREQUENCY),
                type(self._data.get(CONF_CHANGE_FREQUENCY)),
            )
            change_frequency_check, change_frequency_value = _is_int_or_list(
                self._data.get(CONF_CHANGE_FREQUENCY),
                CHANGE_FREQUENCY_MIN,
                CHANGE_FREQUENCY_MAX,
            )
            if change_frequency_check:
                self._data.update({CONF_CHANGE_FREQUENCY: change_frequency_value})
            else:
                self._errors["base"] = ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE
            _LOGGER.debug(
                "Checking Brightness: %s, type: %s",
                self._data.get(CONF_BRIGHTNESS),
                type(self._data.get(CONF_BRIGHTNESS)),
            )
            brightness_check, brightness_value = _is_int_or_list(
                self._data.get(CONF_BRIGHTNESS),
                BRIGHTNESS_MIN,
                BRIGHTNESS_MAX,
            )
            if brightness_check:
                self._data.update({CONF_BRIGHTNESS: brightness_value})
            else:
                self._errors["base"] = ERROR_BRIGHTNESS_NOT_INT_OR_RANGE
            self._data.update(
                {CONF_PRIORITY: round(self._data.get(CONF_PRIORITY, DEFAULT_PRIORITY))}
            )
            self._data.update(
                {
                    CONF_CHANGE_AMOUNT: _overrride_max_change_amount(
                        self._data.get(CONF_CHANGE_AMOUNT),
                        len(self._data.get(CONF_LIGHTS, [])),
                    )
                }
            )
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            # _LOGGER.debug(f"[async_step_scene] self._data: {self._data}")
            if not self._errors:
                if yaml_import:
                    self._data.update({CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_YAML})
                    return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
                if (
                    self._data.get(CONF_COLOR_SELECTOR_MODE, COLOR_SELECTOR_RGB_UI)
                    == COLOR_SELECTOR_RGB_UI
                ):
                    return await self.async_step_color_rgb_ui()
                return await self.async_step_color_yaml()

        return self.async_show_form(
            step_id="scene",
            data_schema=await _async_build_schema(user_input, defaults),
            errors=self._errors,
        )

    async def async_step_color_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration when the user chooses YAML input."""
        self._errors = {}

        # Defaults
        defaults: dict[str, Any] = {}

        if user_input is not None:
            self._data.update(user_input)
            if self._data.get(CONF_COLORS) is None or self._data.get(CONF_COLORS) == {}:
                self._errors["base"] = ERROR_COLORS_IS_BLANK
            if not isinstance(self._data.get(CONF_COLORS), list):
                self._errors["base"] = ERROR_COLORS_MALFORMED
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            # _LOGGER.debug(f"[async_step_color_yaml] self._data: {self._data}")
            if not self._errors:
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(
            step_id="color_yaml",
            data_schema=await _async_build_color_yaml_schema(user_input, defaults),
            errors=self._errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
            },
        )

    async def async_step_color_rgb_ui(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration when the user uses the RGB UI selectors."""
        self._errors = {}

        # Defaults
        defaults = {
            CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
            CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
            CONF_COLOR_ONE_CHANGE_PER_TICK: DEFAULT_COLOR_ONE_CHANGE_PER_TICK,
            CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
            CONF_COLOR_ADD_COLOR: DEFAULT_COLOR_ADD_COLOR,
            CONF_COLOR_DELETE_COLOR: DEFAULT_COLOR_DELETE_COLOR,
        }

        if user_input is not None:
            _LOGGER.debug(
                "Checking Brightnes: %s, type: %s",
                user_input.get(CONF_BRIGHTNESS),
                type(user_input.get(CONF_BRIGHTNESS)),
            )
            brightness_check, brightness_value = _is_int_or_list(
                user_input.get(CONF_BRIGHTNESS),
                BRIGHTNESS_MIN,
                BRIGHTNESS_MAX,
            )
            if brightness_check:
                user_input.update({CONF_BRIGHTNESS: brightness_value})
            else:
                self._errors["base"] = ERROR_BRIGHTNESS_NOT_INT_OR_RANGE
            user_input.update(
                {CONF_COLOR_WEIGHT: round(user_input.get(CONF_COLOR_WEIGHT, DEFAULT_COLOR_WEIGHT))}
            )
            user_input.update(
                {
                    CONF_COLOR_NEARBY_COLORS: round(
                        user_input.get(CONF_COLOR_NEARBY_COLORS, DEFAULT_COLOR_NEARBY_COLORS)
                    )
                }
            )
            for k, v in defaults.items():
                user_input.setdefault(k, v)
            if not self._errors:
                color_uuid = uuid.random_uuid_hex()
                self._data.get(CONF_COLOR_RGB_DICT, {}).update({color_uuid: user_input})
                # _LOGGER.debug(f"[async_step_color_rgb_ui] self._data: {self._data}")
                if user_input.get(CONF_COLOR_ADD_COLOR, False):
                    return await self.async_step_color_rgb_ui()
                self._data.update(
                    {
                        CONF_COLOR_RGB_DICT: _clean_color_rgb_dict(
                            self._data.get(CONF_COLOR_RGB_DICT, {})
                        )
                    }
                )
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
            # _LOGGER.debug(f"[async_step_color_rgb_ui] user_input: {user_input}")

        return self.async_show_form(
            step_id="color_rgb_ui",
            data_schema=await _async_build_color_rgb_ui_schema(user_input, defaults),
            errors=self._errors,
            description_placeholders={
                "color_count": str(len(self._data.get(CONF_COLOR_RGB_DICT, {})) + 1),
            },
        )

    async def async_step_import(
        self, import_config: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import a config entry from configuration.yaml."""
        if import_config:
            import_config.update({CONF_ENTITY_TYPE: ENTITY_SCENE})
            _LOGGER.debug("[async_step_import] import_config: %s", import_config)
        return await self.async_step_scene(user_input=import_config, yaml_import=True)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options callback."""
        return AnimatedScenesOptionsFlowHandler(config_entry)


class AnimatedScenesOptionsFlowHandler(OptionsFlow):
    """Config flow options. Does not actually store these into Options but updates the Config instead."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self.config = config_entry
        self._data = dict(config_entry.data)
        self._errors: dict[str, Any] = {}
        rgb_dict = self._data.get(CONF_COLOR_RGB_DICT)
        if rgb_dict:
            self._rgb_ui_color_keys = list(self._data.get(CONF_COLOR_RGB_DICT, {}).keys())
            self._rgb_ui_color_values = list(self._data.get(CONF_COLOR_RGB_DICT, {}).values())
            self._rgb_ui_color_max = len(self._rgb_ui_color_keys)
        self._rgb_ui_color_index = 0

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""

        if self._data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_ACTIVITY_SENSOR:
            return self.async_abort(reason=ABORT_ACTIVITY_SENSOR_NO_OPTIONS)
        if self._data.get(CONF_ENTITY_TYPE) is None:
            return self.async_abort(reason=ABORT_INTEGRATION_NO_OPTIONS)
        return await self.async_step_scene(user_input=user_input)

    async def async_step_scene(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the scene options step in the options flow.

        Validate and normalize the provided options and either proceed to
        color configuration steps or update the entry data.
        """

        self._errors = {}

        # Defaults
        defaults = {
            CONF_ICON: DEFAULT_ICON,
            CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
            CONF_ANIMATE_BRIGHTNESS: DEFAULT_ANIMATE_BRIGHTNESS,
            CONF_ANIMATE_COLOR: DEFAULT_ANIMATE_COLOR,
            CONF_CHANGE_AMOUNT: DEFAULT_CHANGE_AMOUNT,
            CONF_CHANGE_FREQUENCY: DEFAULT_CHANGE_FREQUENCY,
            CONF_CHANGE_SEQUENCE: DEFAULT_CHANGE_SEQUENCE,
            CONF_RESTORE: DEFAULT_RESTORE,
            CONF_RESTORE_POWER: DEFAULT_RESTORE_POWER,
            CONF_IGNORE_OFF: DEFAULT_IGNORE_OFF,
            CONF_TRANSITION: DEFAULT_TRANSITION,
            CONF_PRIORITY: DEFAULT_PRIORITY,
        }

        if user_input is not None:
            self._data.update(user_input)
            self._data.update({CONF_ENTITY_TYPE: ENTITY_SCENE})
            _LOGGER.debug(
                "Checking Change Amount: %s, type: %s",
                self._data.get(CONF_CHANGE_AMOUNT),
                type(self._data.get(CONF_CHANGE_AMOUNT)),
            )
            change_amount_check, change_amount_value = _is_int_list_or_all(
                self._data.get(CONF_CHANGE_AMOUNT),
                CHANGE_AMOUNT_MIN,
                CHANGE_AMOUNT_MAX,
            )
            if change_amount_check:
                self._data.update({CONF_CHANGE_AMOUNT: change_amount_value})
            else:
                self._errors["base"] = ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL
            _LOGGER.debug(
                "Checking Transition: %s, type: %s",
                self._data.get(CONF_TRANSITION),
                type(self._data.get(CONF_TRANSITION)),
            )
            transition_check, transition_value = _is_int_or_list(
                self._data.get(CONF_TRANSITION),
                TRANSITION_MIN,
                TRANSITION_MAX,
            )
            if transition_check:
                self._data.update({CONF_TRANSITION: transition_value})
            else:
                self._errors["base"] = ERROR_TRANSITION_NOT_INT_OR_RANGE
            _LOGGER.debug(
                "Checking Change Frequency: %s, type: %s",
                self._data.get(CONF_CHANGE_FREQUENCY),
                type(self._data.get(CONF_CHANGE_FREQUENCY)),
            )
            change_frequency_check, change_frequency_value = _is_int_or_list(
                self._data.get(CONF_CHANGE_FREQUENCY),
                CHANGE_FREQUENCY_MIN,
                CHANGE_FREQUENCY_MAX,
            )
            if change_frequency_check:
                self._data.update({CONF_CHANGE_FREQUENCY: change_frequency_value})
            else:
                self._errors["base"] = ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE
            _LOGGER.debug(
                "Checking Brightness: %s, type: %s",
                self._data.get(CONF_BRIGHTNESS),
                type(self._data.get(CONF_BRIGHTNESS)),
            )
            brightness_check, brightness_value = _is_int_or_list(
                self._data.get(CONF_BRIGHTNESS),
                BRIGHTNESS_MIN,
                BRIGHTNESS_MAX,
            )
            if brightness_check:
                self._data.update({CONF_BRIGHTNESS: brightness_value})
            else:
                self._errors["base"] = ERROR_BRIGHTNESS_NOT_INT_OR_RANGE
            self._data.update(
                {CONF_PRIORITY: round(self._data.get(CONF_PRIORITY, DEFAULT_PRIORITY))}
            )
            self._data.update(
                {
                    CONF_CHANGE_AMOUNT: _overrride_max_change_amount(
                        self._data.get(CONF_CHANGE_AMOUNT),
                        len(self._data.get(CONF_LIGHTS, [])),
                    )
                }
            )
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            # _LOGGER.debug(f"[async_init_user] self._data: {self._data}")
            if not self._errors:
                if (
                    self._data.get(CONF_COLOR_SELECTOR_MODE, COLOR_SELECTOR_RGB_UI)
                    == COLOR_SELECTOR_RGB_UI
                ):
                    return await self.async_step_color_rgb_ui()
                return await self.async_step_color_yaml()

        return self.async_show_form(
            step_id="scene",
            data_schema=await _async_build_schema(user_input, self._data, options_flow=True),
            errors=self._errors,
            description_placeholders={"scene_name": self._data[CONF_NAME]},
        )

    async def async_step_color_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration in YAML mode within the options flow."""
        self._errors = {}

        # Defaults
        defaults: dict[str, Any] = {}

        if user_input is not None:
            self._data.update(user_input)
            if self._data.get(CONF_COLORS) is None or self._data.get(CONF_COLORS) == {}:
                self._errors["base"] = ERROR_COLORS_IS_BLANK
            if not isinstance(self._data.get(CONF_COLORS), list):
                self._errors["base"] = ERROR_COLORS_MALFORMED
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            # _LOGGER.debug(f"[async_step_color_yaml] self._data: {self._data}")
            if not self._errors:
                self._data.update({CONF_COLOR_RGB_DICT: {}})
                self.hass.config_entries.async_update_entry(
                    self.config, data=self._data, options=self.config.options
                )
                await self.hass.config_entries.async_reload(self.config.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="color_yaml",
            data_schema=await _async_build_color_yaml_schema(user_input, self._data),
            errors=self._errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
            },
        )

    async def async_step_color_rgb_ui(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration using the RGB UI selectors in options."""
        self._errors = {}

        # Defaults
        defaults = {
            CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
            CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
            CONF_COLOR_ONE_CHANGE_PER_TICK: DEFAULT_COLOR_ONE_CHANGE_PER_TICK,
            CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
            CONF_COLOR_ADD_COLOR: DEFAULT_COLOR_ADD_COLOR,
            CONF_COLOR_DELETE_COLOR: DEFAULT_COLOR_DELETE_COLOR,
        }
        if self._rgb_ui_color_index + 1 <= self._rgb_ui_color_max:
            color_data = self._rgb_ui_color_values[self._rgb_ui_color_index]
        else:
            color_data = {}

        if user_input is not None:
            color_data.update(user_input)
            _LOGGER.debug(
                "Checking Brightnes: %s, type: %s",
                color_data.get(CONF_BRIGHTNESS),
                type(color_data.get(CONF_BRIGHTNESS)),
            )
            brightness_check, brightness_value = _is_int_or_list(
                color_data.get(CONF_BRIGHTNESS),
                BRIGHTNESS_MIN,
                BRIGHTNESS_MAX,
            )
            if brightness_check:
                color_data.update({CONF_BRIGHTNESS: brightness_value})
            else:
                self._errors["base"] = ERROR_BRIGHTNESS_NOT_INT_OR_RANGE
            color_data.update({CONF_COLOR_WEIGHT: round(color_data.get(CONF_COLOR_WEIGHT))})
            color_data.update(
                {CONF_COLOR_NEARBY_COLORS: round(color_data.get(CONF_COLOR_NEARBY_COLORS))}
            )
            for k, v in defaults.items():
                color_data.setdefault(k, v)
            if not self._errors:
                if self._rgb_ui_color_index + 1 <= self._rgb_ui_color_max:
                    self._data.get(CONF_COLOR_RGB_DICT, {}).update(
                        {self._rgb_ui_color_keys[self._rgb_ui_color_index]: color_data}
                    )
                else:
                    color_uuid = uuid.random_uuid_hex()
                    self._data.get(CONF_COLOR_RGB_DICT, {}).update({color_uuid: color_data})
                if self._rgb_ui_color_index + 1 < self._rgb_ui_color_max or (
                    self._rgb_ui_color_index + 1 >= self._rgb_ui_color_max
                    and color_data.get(CONF_COLOR_ADD_COLOR, False)
                ):
                    # _LOGGER.debug(f"[async_step_color_rgb_ui] self._data: {self._data}")
                    self._rgb_ui_color_index += 1
                    return await self.async_step_color_rgb_ui()
                self._data.update({CONF_COLORS: {}})
                self._data.update(
                    {
                        CONF_COLOR_RGB_DICT: _clean_color_rgb_dict(
                            self._data.get(CONF_COLOR_RGB_DICT, {})
                        )
                    }
                )
                # _LOGGER.debug(f"[async_step_color_rgb_ui] self._data: {self._data}")
                self.hass.config_entries.async_update_entry(
                    self.config, data=self._data, options=self.config.options
                )
                await self.hass.config_entries.async_reload(self.config.entry_id)
                return self.async_create_entry(title="", data={})
            # _LOGGER.debug(f"[async_step_color_rgb_ui] color_data: {color_data}")

        return self.async_show_form(
            step_id="color_rgb_ui",
            data_schema=await _async_build_color_rgb_ui_schema(
                user_input,
                color_data,
                options_flow=True,
                is_last_color=(self._rgb_ui_color_index + 1 >= self._rgb_ui_color_max),
            ),
            errors=self._errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
                "color_count": str(self._rgb_ui_color_index + 1),
                "color_max": str(self._rgb_ui_color_max),
            },
        )
