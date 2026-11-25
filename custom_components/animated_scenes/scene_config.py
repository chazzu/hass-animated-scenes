"""Shared scene configuration normalization for Animated Scenes."""

from __future__ import annotations

from collections.abc import Callable
import copy
import math
from typing import Any

from homeassistant.components.light import (
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
)
from homeassistant.const import CONF_BRIGHTNESS, CONF_ICON, CONF_LIGHTS, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_COLOR_TEMP,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CHANGE_AMOUNT_MAX,
    CHANGE_AMOUNT_MIN,
    CHANGE_FREQUENCY_MAX,
    CHANGE_FREQUENCY_MIN,
    CHANGE_FREQUENCY_REPEAT_MIN,
    COLOR_TEMPERATURE_MAX,
    CONF_ANIMATE_BRIGHTNESS,
    CONF_ANIMATE_COLOR,
    CONF_ANIMATED_SCENE_SWITCH,
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_CHANGE_SEQUENCE,
    CONF_COLOR,
    CONF_COLOR_ADD_COLOR,
    CONF_COLOR_DELETE_COLOR,
    CONF_COLOR_NEARBY_COLORS,
    CONF_COLOR_ONE_CHANGE_PER_TICK,
    CONF_COLOR_RGB,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_COLOR_TYPE,
    CONF_COLOR_WEIGHT,
    CONF_COLORS,
    CONF_ENTITY_TYPE,
    CONF_IGNORE_OFF,
    CONF_PLATFORM,
    CONF_PRIORITY,
    CONF_RESTORE,
    CONF_RESTORE_POWER,
    CONF_SKIP_RESTORE,
    CONF_TRANSITION,
    DEFAULT_ANIMATE_BRIGHTNESS,
    DEFAULT_ANIMATE_COLOR,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CHANGE_AMOUNT,
    DEFAULT_CHANGE_FREQUENCY,
    DEFAULT_CHANGE_SEQUENCE,
    DEFAULT_COLOR_NEARBY_COLORS,
    DEFAULT_COLOR_ONE_CHANGE_PER_TICK,
    DEFAULT_COLOR_WEIGHT,
    DEFAULT_IGNORE_OFF,
    DEFAULT_PRIORITY,
    DEFAULT_RESTORE,
    DEFAULT_RESTORE_POWER,
    DEFAULT_TRANSITION,
    DOMAIN,
    ENTITY_SCENE,
    ERROR_BRIGHTNESS_NOT_INT_OR_RANGE,
    ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL,
    ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE,
    ERROR_COLORS_MALFORMED,
    ERROR_MUST_SELECT_LIGHTS,
    ERROR_PRIORITY_NOT_INT,
    ERROR_TRANSITION_NOT_INT_OR_RANGE,
    PRIORITY_MAX,
    PRIORITY_MIN,
    TRANSITION_MAX,
    TRANSITION_MIN,
)

SCENE_DEFAULTS: dict[str, Any] = {
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

# Config-entry keys that describe the entry or its UI, not the running animation.
ENTRY_ONLY_KEYS: tuple[str, ...] = (
    CONF_PLATFORM,
    CONF_ICON,
    CONF_ENTITY_TYPE,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
)

NUMBER_RANGE_PATTERN = r"^\[\s*(?:\d+(?:\.\d+)?|\.\d+)\s*,\s*(?:\d+(?:\.\d+)?|\.\d+)\s*\]$"
INT_RANGE_PATTERN = r"^\[\s*\d+\s*,\s*\d+\s*\]$"


def _strlist_to_list(value: str) -> list[str]:
    """Convert a bracketed comma-separated string into a trimmed item list.

    Args:
        value: A bracketed comma-separated string such as ``"[1, 2]"``.

    Returns:
        The trimmed list items between brackets. Malformed empty items are
        preserved for the caller's typed validation to reject.
    """
    return [item.strip() for item in value.strip("][").split(",")]


def scene_name_exists(hass: HomeAssistant, name: str, exclude_entry_id: str | None = None) -> bool:
    """Return whether another scene config entry already uses a name.

    Args:
        hass: Home Assistant instance containing config entries.
        name: Proposed runtime scene name; surrounding whitespace is ignored.
        exclude_entry_id: Entry id to ignore while validating an options rename.

    Returns:
        True when another Animated Scenes scene entry uses the proposed name.

    """
    stripped_name = name.strip()
    return any(
        entry.entry_id != exclude_entry_id
        and entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE
        and str(entry.data.get(CONF_NAME)).strip() == stripped_name
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


def runtime_scene_config(data: dict[str, Any]) -> dict[str, Any]:
    """Return scene data without the keys that only describe the config entry.

    Args:
        data: Config-entry or flow scene data.

    Returns:
        A shallow copy of ``data`` without ``ENTRY_ONLY_KEYS``.

    """
    return {key: value for key, value in data.items() if key not in ENTRY_ONLY_KEYS}


def _safe_coerce(target: type[float | int]) -> Callable[[Any], float | int]:
    """Build a numeric coercer that reports every conversion failure as invalid.

    ``vol.Coerce`` lets ``OverflowError`` escape (for example ``float(10**400)``
    or ``int(float("inf"))``), which would surface as an unexpected exception
    instead of a validation error.

    Args:
        target: Numeric type to convert values to.

    Returns:
        A validator that converts a value to ``target`` or raises ``vol.Invalid``.

    """

    def _coerce(value: Any) -> float | int:
        """Convert a value to the target numeric type.

        Args:
            value: Raw value from a flow, service call, or YAML.

        Returns:
            The converted value.

        Raises:
            vol.Invalid: If the value cannot be converted.

        """
        try:
            return target(value)
        except (OverflowError, TypeError, ValueError) as err:
            raise vol.Invalid(f"expected {target.__name__}") from err

    return _coerce


_coerce_float = _safe_coerce(float)
_coerce_int = _safe_coerce(int)
_BYTE_SCHEMA = vol.All(_coerce_int, vol.Range(min=0, max=255))
_SMALL_FLOAT_SCHEMA = vol.All(_coerce_float, vol.Range(min=0, max=1))


def _whole_float_to_int(value: float) -> int:
    """Convert a whole float to int or raise for fractional values.

    Args:
        value: Float value to convert to an integer.

    Returns:
        Integer representation of the float.

    Raises:
        vol.Invalid: If the float has a fractional component.

    """
    if not value.is_integer():
        raise vol.Invalid("value must be a whole number")
    return int(value)


def _priority_to_int(value: Any) -> int:
    """Convert an integral priority value to int with its flow error key.

    Args:
        value: Priority value supplied through a flow or service call.

    Returns:
        Integer representation of the priority.

    Raises:
        vol.Invalid: If the value is not numeric, has a fractional component,
            or is outside ``PRIORITY_MIN`` to ``PRIORITY_MAX``.

    """
    try:
        # Integers skip the float check for fractions. Either path is exact for
        # the allowed range, which stays well below 2**53.
        priority = value if isinstance(value, int) else _whole_float_to_int(float(value))
    except (OverflowError, TypeError, ValueError, vol.Invalid) as err:
        raise vol.Invalid(ERROR_PRIORITY_NOT_INT) from err
    if not PRIORITY_MIN <= priority <= PRIORITY_MAX:
        raise vol.Invalid(ERROR_PRIORITY_NOT_INT)
    return int(priority)


def _lift_zero_frequency_range(value: Any) -> Any:
    """Replace a zero bound in a frequency range with the repeating minimum.

    Older versions accepted ranges such as ``[0, 5]``. A selected delay of zero
    would update lights without pausing, so those ranges start at the minimum.

    Args:
        value: Raw scalar, sequence, or bracketed-string frequency value.

    Returns:
        A sorted numeric range when a range's lower bound is zero, otherwise
        the unchanged value for normal validation.

    """
    items = value
    if isinstance(value, str):
        stripped = value.strip()
        if not (stripped.startswith("[") and stripped.endswith("]") and stripped.count(",") == 1):
            return value
        items = _strlist_to_list(stripped)
    if not isinstance(items, list | tuple) or len(items) != 2:
        return value
    try:
        bounds = [float(item) for item in items]
    except OverflowError, TypeError, ValueError:
        return value
    if min(bounds) != CHANGE_FREQUENCY_MIN:
        return value
    return sorted(
        CHANGE_FREQUENCY_REPEAT_MIN if bound == CHANGE_FREQUENCY_MIN else bound for bound in bounds
    )


BRIGHTNESS_VALUE_SCHEMA = vol.All(
    _coerce_float,
    _whole_float_to_int,
    vol.Range(min=BRIGHTNESS_MIN, max=BRIGHTNESS_MAX),
)
TRANSITION_VALUE_SCHEMA = vol.All(_coerce_float, vol.Range(min=TRANSITION_MIN, max=TRANSITION_MAX))
CHANGE_FREQUENCY_VALUE_SCHEMA = vol.All(
    _coerce_float,
    vol.Any(
        vol.Equal(CHANGE_FREQUENCY_MIN),
        vol.Range(min=CHANGE_FREQUENCY_REPEAT_MIN, max=CHANGE_FREQUENCY_MAX),
    ),
)
CHANGE_FREQUENCY_RANGE_VALUE_SCHEMA = vol.All(
    _coerce_float,
    vol.Range(
        min=CHANGE_FREQUENCY_REPEAT_MIN,
        max=CHANGE_FREQUENCY_MAX,
    ),
)
CHANGE_AMOUNT_VALUE_SCHEMA = vol.All(
    _coerce_float,
    _whole_float_to_int,
    vol.Range(min=CHANGE_AMOUNT_MIN, max=CHANGE_AMOUNT_MAX),
)
PRIORITY_VALUE_SCHEMA = _priority_to_int
BRIGHTNESS_RANGE_SCHEMA = vol.Any(
    BRIGHTNESS_VALUE_SCHEMA,
    vol.All(
        vol.ExactSequence(
            (
                BRIGHTNESS_VALUE_SCHEMA,
                BRIGHTNESS_VALUE_SCHEMA,
            )
        ),
        sorted,
    ),
    vol.All(
        vol.Match(INT_RANGE_PATTERN),
        _strlist_to_list,
        vol.ExactSequence((BRIGHTNESS_VALUE_SCHEMA, BRIGHTNESS_VALUE_SCHEMA)),
        sorted,
    ),
)
TRANSITION_RANGE_SCHEMA = vol.Any(
    TRANSITION_VALUE_SCHEMA,
    vol.ExactSequence((TRANSITION_VALUE_SCHEMA, TRANSITION_VALUE_SCHEMA)),
    vol.All(
        vol.Match(NUMBER_RANGE_PATTERN),
        _strlist_to_list,
        vol.ExactSequence((TRANSITION_VALUE_SCHEMA, TRANSITION_VALUE_SCHEMA)),
    ),
)
CHANGE_FREQUENCY_RANGE_SCHEMA = vol.All(
    _lift_zero_frequency_range,
    vol.Any(
        CHANGE_FREQUENCY_VALUE_SCHEMA,
        vol.ExactSequence(
            (
                CHANGE_FREQUENCY_RANGE_VALUE_SCHEMA,
                CHANGE_FREQUENCY_RANGE_VALUE_SCHEMA,
            )
        ),
        vol.All(
            vol.Match(NUMBER_RANGE_PATTERN),
            _strlist_to_list,
            vol.ExactSequence(
                (CHANGE_FREQUENCY_RANGE_VALUE_SCHEMA, CHANGE_FREQUENCY_RANGE_VALUE_SCHEMA)
            ),
        ),
    ),
)
CHANGE_AMOUNT_RANGE_SCHEMA = vol.Any(
    "all",
    CHANGE_AMOUNT_VALUE_SCHEMA,
    vol.All(
        vol.Match(INT_RANGE_PATTERN),
        _strlist_to_list,
        vol.ExactSequence((CHANGE_AMOUNT_VALUE_SCHEMA, CHANGE_AMOUNT_VALUE_SCHEMA)),
    ),
    vol.ExactSequence(
        (
            CHANGE_AMOUNT_VALUE_SCHEMA,
            CHANGE_AMOUNT_VALUE_SCHEMA,
        )
    ),
)

COLOR_GROUP_SCHEMA = {
    vol.Optional(CONF_BRIGHTNESS, default=DEFAULT_BRIGHTNESS): BRIGHTNESS_RANGE_SCHEMA,
    vol.Optional(CONF_COLOR_WEIGHT, default=DEFAULT_COLOR_WEIGHT): vol.Range(min=0, max=255),
    vol.Optional(CONF_COLOR_ONE_CHANGE_PER_TICK, default=DEFAULT_COLOR_ONE_CHANGE_PER_TICK): bool,
    vol.Optional(
        CONF_COLOR_NEARBY_COLORS,
        default=DEFAULT_COLOR_NEARBY_COLORS,
    ): vol.Range(min=0, max=10),
}


def validate_start_service_weights(data: dict[str, Any]) -> dict[str, Any]:
    """Require a selectable color only when colors are chosen at random.

    Sequence mode walks the colors in order, so zero weights are harmless there.

    Args:
        data: Validated start service data.

    Returns:
        The unchanged data when the weights are usable.

    Raises:
        vol.Invalid: If random mode has no color with a positive total weight.

    """
    if data.get(CONF_CHANGE_SEQUENCE):
        return data
    if sum(color[CONF_COLOR_WEIGHT] for color in data.get(CONF_COLORS, [])) <= 0:
        raise vol.Invalid(ERROR_COLORS_MALFORMED)
    return data


START_SERVICE_CONFIG = {
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_IGNORE_OFF, default=DEFAULT_IGNORE_OFF): bool,
    vol.Optional(CONF_RESTORE, default=DEFAULT_RESTORE): bool,
    vol.Optional(CONF_RESTORE_POWER, default=DEFAULT_RESTORE_POWER): bool,
    vol.Optional(CONF_BRIGHTNESS, default=DEFAULT_BRIGHTNESS): BRIGHTNESS_RANGE_SCHEMA,
    vol.Optional(CONF_TRANSITION, default=DEFAULT_TRANSITION): TRANSITION_RANGE_SCHEMA,
    vol.Optional(CONF_CHANGE_FREQUENCY, default=DEFAULT_CHANGE_FREQUENCY): (
        CHANGE_FREQUENCY_RANGE_SCHEMA
    ),
    vol.Optional(CONF_CHANGE_AMOUNT, default=DEFAULT_CHANGE_AMOUNT): CHANGE_AMOUNT_RANGE_SCHEMA,
    vol.Optional(CONF_CHANGE_SEQUENCE, default=DEFAULT_CHANGE_SEQUENCE): bool,
    vol.Optional(CONF_ANIMATE_BRIGHTNESS, default=DEFAULT_ANIMATE_BRIGHTNESS): bool,
    vol.Optional(CONF_ANIMATE_COLOR, default=DEFAULT_ANIMATE_COLOR): bool,
    vol.Optional(CONF_PRIORITY, default=DEFAULT_PRIORITY): PRIORITY_VALUE_SCHEMA,
    vol.Required(CONF_LIGHTS): cv.entity_ids,
    vol.Optional(CONF_COLORS, default=[]): vol.All(
        cv.ensure_list,
        vol.Length(min=1),
        [
            vol.Any(
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGB_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((_BYTE_SCHEMA,) * 3)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGBW_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((_BYTE_SCHEMA,) * 4)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_RGBWW_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple), vol.ExactSequence((_BYTE_SCHEMA,) * 5)
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_XY_COLOR,
                        vol.Required(CONF_COLOR): vol.All(
                            vol.Coerce(tuple),
                            vol.ExactSequence((_SMALL_FLOAT_SCHEMA, _SMALL_FLOAT_SCHEMA)),
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
                                    vol.All(_coerce_float, vol.Range(min=0, max=360)),
                                    vol.All(_coerce_float, vol.Range(min=0, max=100)),
                                )
                            ),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_COLOR_TEMP,
                        vol.Required(CONF_COLOR): vol.All(
                            _coerce_int,
                            vol.Range(min=1, max=COLOR_TEMPERATURE_MAX),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
                vol.Schema(
                    {
                        vol.Required(CONF_COLOR_TYPE): ATTR_COLOR_TEMP_KELVIN,
                        vol.Required(CONF_COLOR): vol.All(
                            _coerce_int,
                            vol.Range(min=0, max=COLOR_TEMPERATURE_MAX),
                        ),
                    }
                ).extend(COLOR_GROUP_SCHEMA),
            )
        ],
    ),
}

START_SERVICE_SCHEMA = vol.All(vol.Schema(START_SERVICE_CONFIG), validate_start_service_weights)
STOP_SERVICE_SCHEMA = vol.Schema({vol.Required(CONF_NAME): cv.string})
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


def is_int(value: Any) -> tuple[bool, Any]:
    """Return whether value is integer-like and its normalized value."""
    if value is None or not isinstance(value, int | float | str):
        return False, value
    if isinstance(value, int):
        # Keep integers exact; a float round-trip can overflow or round them.
        return True, int(value)
    try:
        parsed = float(value)
    except OverflowError, TypeError, ValueError:
        return False, value
    if parsed.is_integer():
        return True, int(parsed)
    return False, value


def is_number(value: Any) -> tuple[bool, Any]:
    """Return whether value is numeric and its normalized value."""
    is_int_check, is_int_value = is_int(value)
    if is_int_check:
        return True, is_int_value
    if value is None or not isinstance(value, int | float | str):
        return False, value
    try:
        parsed = float(value)
    except OverflowError, TypeError, ValueError:
        return False, value
    if not math.isfinite(parsed):
        return False, value
    return True, parsed


def list_or_int_to_str(value: Any) -> Any:
    """Return a UI string representation for a finite number or two-item list."""
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    is_number_check, number_value = is_number(value)
    if is_number_check:
        return str(number_value)
    return value


def is_int_or_list(
    value: Any, min_value: int | None = None, max_value: int | None = None
) -> tuple[bool, Any]:
    """Validate and normalize an int or two-item integer range."""
    if value is None:
        return True, value
    is_int_check, is_int_value = is_int(value)
    if is_int_check:
        if (min_value is None or is_int_value >= min_value) and (
            max_value is None or is_int_value <= max_value
        ):
            return True, is_int_value
        return False, value
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]") and value.count(",") == 1:
            value = _strlist_to_list(value)
        else:
            return False, value
    if isinstance(value, list | tuple) and len(value) == 2:
        is_first, first = is_int(value[0])
        is_second, second = is_int(value[1])
        if not (is_first and is_second):
            return False, value
        normalized = [min(first, second), max(first, second)]
        if (min_value is None or min(normalized) >= min_value) and (
            max_value is None or max(normalized) <= max_value
        ):
            if normalized[0] == normalized[1]:
                return True, normalized[0]
            return True, normalized
    return False, value


def is_number_or_list(
    value: Any,
    min_value: float | None = None,
    max_value: float | None = None,
    min_included: bool = True,
) -> tuple[bool, Any]:
    """Validate and normalize a number or two-item numeric range."""
    if value is None:
        return True, value
    is_number_check, number_value = is_number(value)
    if is_number_check:
        above_min = min_value is None or (
            number_value >= min_value if min_included else number_value > min_value
        )
        if above_min and (max_value is None or number_value <= max_value):
            return True, number_value
        return False, value
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]") and value.count(",") == 1:
            value = _strlist_to_list(value)
        else:
            return False, value
    if isinstance(value, list | tuple) and len(value) == 2:
        is_first, first = is_number(value[0])
        is_second, second = is_number(value[1])
        if not (is_first and is_second):
            return False, value
        normalized = [min(first, second), max(first, second)]
        lowest = min(normalized)
        above_min = min_value is None or (
            lowest >= min_value if min_included else lowest > min_value
        )
        if above_min and (max_value is None or max(normalized) <= max_value):
            if normalized[0] == normalized[1]:
                return True, normalized[0]
            return True, normalized
    return False, value


def is_int_list_or_all(
    value: Any, min_value: int | None = None, max_value: int | None = None
) -> tuple[bool, Any]:
    """Validate and normalize an int, two-item integer range, or all."""
    is_valid, normalized = is_int_or_list(value, min_value, max_value)
    if is_valid:
        return True, normalized
    if isinstance(value, str) and value.strip() == "all":
        return True, "all"
    return False, value


def normalize_scene_input(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize config-flow or service scene data and raise vol.Invalid on errors."""
    normalized = dict(data)
    for key, default in SCENE_DEFAULTS.items():
        normalized.setdefault(key, default)

    try:
        lights = cv.entity_ids(normalized.get(CONF_LIGHTS, []))
    except vol.Invalid as err:
        raise vol.Invalid(ERROR_MUST_SELECT_LIGHTS) from err
    if len(lights) == 0:
        raise vol.Invalid(ERROR_MUST_SELECT_LIGHTS)
    normalized[CONF_LIGHTS] = lights

    change_ok, change_value = is_int_list_or_all(
        normalized.get(CONF_CHANGE_AMOUNT), CHANGE_AMOUNT_MIN, CHANGE_AMOUNT_MAX
    )
    if not change_ok:
        raise vol.Invalid(ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL)
    normalized[CONF_CHANGE_AMOUNT] = change_value

    transition_ok, transition_value = is_number_or_list(
        normalized.get(CONF_TRANSITION), TRANSITION_MIN, TRANSITION_MAX
    )
    if not transition_ok:
        raise vol.Invalid(ERROR_TRANSITION_NOT_INT_OR_RANGE)
    normalized[CONF_TRANSITION] = transition_value

    raw_frequency = _lift_zero_frequency_range(normalized.get(CONF_CHANGE_FREQUENCY))
    scalar_ok, scalar_frequency = is_number(raw_frequency)
    if scalar_ok and scalar_frequency == CHANGE_FREQUENCY_MIN:
        frequency_ok, frequency_value = True, scalar_frequency
    else:
        frequency_ok, frequency_value = is_number_or_list(
            raw_frequency,
            CHANGE_FREQUENCY_REPEAT_MIN,
            CHANGE_FREQUENCY_MAX,
        )
    if not frequency_ok:
        raise vol.Invalid(ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE)
    normalized[CONF_CHANGE_FREQUENCY] = frequency_value

    brightness_ok, brightness_value = is_int_or_list(
        normalized.get(CONF_BRIGHTNESS), BRIGHTNESS_MIN, BRIGHTNESS_MAX
    )
    if not brightness_ok:
        raise vol.Invalid(ERROR_BRIGHTNESS_NOT_INT_OR_RANGE)
    normalized[CONF_BRIGHTNESS] = brightness_value
    try:
        normalized[CONF_PRIORITY] = PRIORITY_VALUE_SCHEMA(
            normalized.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        )
    except vol.Invalid as err:
        raise vol.Invalid(ERROR_PRIORITY_NOT_INT) from err
    return normalized


def clean_color_rgb_dict(color_rgb_dict: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Remove RGB UI-only helper keys from stored color data."""
    cleaned = {}
    for key, color in color_rgb_dict.items():
        if color.get(CONF_COLOR_DELETE_COLOR, False):
            continue
        cleaned_color = copy.deepcopy(color)
        cleaned_color.pop(CONF_COLOR_ADD_COLOR, None)
        cleaned_color.pop(CONF_COLOR_DELETE_COLOR, None)
        cleaned[key] = cleaned_color
    return cleaned


def build_colors_from_rgb_dict(color_rgb_dict: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert RGB UI storage into the runtime colors list."""
    color_list = [copy.deepcopy(color) for color in color_rgb_dict.values()]
    for color in color_list:
        color[CONF_COLOR_TYPE] = CONF_COLOR_RGB
    return color_list


def validate_start_service_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate runtime start service data."""
    return START_SERVICE_SCHEMA(dict(data))
