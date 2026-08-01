"""Tests for shared Animated Scenes configuration normalization."""

from __future__ import annotations

from homeassistant.const import CONF_BRIGHTNESS, CONF_LIGHTS, CONF_NAME
import pytest
import voluptuous as vol

from custom_components.animated_scenes import scene_config
from custom_components.animated_scenes.const import (
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_COLOR_RGB,
    CONF_COLOR_RGB_DICT,
    CONF_COLORS,
    CONF_ENTITY_TYPE,
    CONF_PRIORITY,
    CONF_TRANSITION,
    DEFAULT_ANIMATE_BRIGHTNESS,
    DEFAULT_ANIMATE_COLOR,
    DEFAULT_CHANGE_SEQUENCE,
    DEFAULT_IGNORE_OFF,
    DEFAULT_PRIORITY,
    DEFAULT_RESTORE,
    DEFAULT_RESTORE_POWER,
)
from custom_components.animated_scenes.scene_config import (
    build_colors_from_rgb_dict,
    clean_color_rgb_dict,
    normalize_scene_input,
    validate_start_service_data,
)


def _base_input() -> dict[str, object]:
    """Return minimal valid scene input."""
    return {
        CONF_NAME: "Spooky",
        CONF_LIGHTS: ["light.one", "light.two"],
        CONF_CHANGE_AMOUNT: "3",
        "transition": "1",
        "change_frequency": "1",
        CONF_BRIGHTNESS: "255",
        CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
    }


def test_normalize_scene_input_clamps_change_amount_to_all() -> None:
    """Normalize change_amount larger than selected lights to all."""
    result = normalize_scene_input(_base_input())

    assert result[CONF_CHANGE_AMOUNT] == "all"


def test_normalize_scene_input_clamps_change_amount_range_without_mutating_input() -> None:
    """Clamp oversized change_amount ranges without mutating caller data."""
    data = _base_input()
    change_amount = [1, 3]
    data[CONF_CHANGE_AMOUNT] = change_amount

    result = normalize_scene_input(data)

    assert result[CONF_CHANGE_AMOUNT] == [1, 2]
    assert change_amount == [1, 3]


def test_normalize_scene_input_adds_defaults() -> None:
    """Add integration defaults exactly once in shared normalization."""
    result = normalize_scene_input(_base_input())

    assert result["animate_brightness"] is DEFAULT_ANIMATE_BRIGHTNESS
    assert result["animate_color"] is DEFAULT_ANIMATE_COLOR
    assert result["change_sequence"] is DEFAULT_CHANGE_SEQUENCE
    assert result["ignore_off"] is DEFAULT_IGNORE_OFF
    assert result["priority"] == DEFAULT_PRIORITY
    assert result["restore"] is DEFAULT_RESTORE
    assert result["restore_power"] is DEFAULT_RESTORE_POWER


def test_normalize_scene_input_accepts_fractional_timing_values() -> None:
    """Accept decimal transition and frequency values from config flows."""
    data = _base_input()
    data[CONF_TRANSITION] = "[0.5, 1.0]"
    data[CONF_CHANGE_FREQUENCY] = "0.5"

    result = normalize_scene_input(data)

    assert result[CONF_TRANSITION] == [0.5, 1]
    assert result[CONF_CHANGE_FREQUENCY] == 0.5


def test_normalize_scene_input_preserves_config_flow_metadata() -> None:
    """Allow config-flow-only fields to pass through shared normalization."""
    data = _base_input()
    data.update(
        {
            CONF_ENTITY_TYPE: "scene",
            CONF_COLOR_RGB_DICT: {},
            "icon": "mdi:palette",
            "color_selector_mode": "color_rgb_ui",
        }
    )

    result = normalize_scene_input(data)

    assert result[CONF_ENTITY_TYPE] == "scene"
    assert result[CONF_COLOR_RGB_DICT] == {}
    assert result["icon"] == "mdi:palette"
    assert result["color_selector_mode"] == "color_rgb_ui"


def test_normalize_scene_input_accepts_fractional_runtime_timings() -> None:
    """Allow UI-entered timings that the start service schema already accepts."""
    data = _base_input()
    data["transition"] = "0.5"
    data["change_frequency"] = "[0.25, 1.5]"

    result = normalize_scene_input(data)
    service_result = validate_start_service_data(result)

    assert result["transition"] == 0.5
    assert result["change_frequency"] == [0.25, 1.5]
    assert service_result["transition"] == 0.5
    assert service_result["change_frequency"] == [0.25, 1.5]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (CONF_CHANGE_AMOUNT, "bad", "change_amount_not_int_or_all"),
        ("transition", "[1, bad]", "transition_not_int_or_range"),
        (CONF_BRIGHTNESS, "300", "brightness_not_int_or_range"),
        (CONF_LIGHTS, None, "must_select_lights"),
        (CONF_PRIORITY, "high", "priority_not_int"),
    ],
)
def test_normalize_scene_input_reports_specific_errors(
    field: str, value: object, message: str
) -> None:
    """Return the same error keys used by config and options flows."""
    data = _base_input()
    data[field] = value

    with pytest.raises(vol.Invalid, match=message):
        normalize_scene_input(data)


def test_validate_start_service_data_accepts_normalized_scene_data() -> None:
    """Validate start service data through the shared runtime schema."""
    result = validate_start_service_data(normalize_scene_input(_base_input()))

    assert result[CONF_NAME] == "Spooky"
    assert result[CONF_CHANGE_AMOUNT] == "all"


def test_validate_start_service_data_accepts_templated_numeric_strings() -> None:
    """Accept string numeric values from automations before runtime startup."""
    data = normalize_scene_input(_base_input())
    data[CONF_BRIGHTNESS] = "255"
    data[CONF_TRANSITION] = "0.5"
    data[CONF_CHANGE_FREQUENCY] = "0.5"

    result = validate_start_service_data(data)

    assert result[CONF_BRIGHTNESS] == 255
    assert result[CONF_TRANSITION] == 0.5
    assert result[CONF_CHANGE_FREQUENCY] == 0.5


def test_validate_start_service_data_accepts_templated_numeric_ranges() -> None:
    """Accept bracketed numeric range strings from automation service data."""
    data = normalize_scene_input(_base_input())
    data[CONF_BRIGHTNESS] = "[70, 255]"
    data[CONF_TRANSITION] = "[0.5, 1.0]"
    data[CONF_CHANGE_FREQUENCY] = "[0.25, 1.5]"

    result = validate_start_service_data(data)

    assert result[CONF_BRIGHTNESS] == [70, 255]
    assert result[CONF_TRANSITION] == [0.5, 1.0]
    assert result[CONF_CHANGE_FREQUENCY] == [0.25, 1.5]


def test_validate_start_service_data_accepts_hourly_change_frequency() -> None:
    """Accept change_frequency values up to one hour."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_FREQUENCY] = "3600"

    result = validate_start_service_data(data)

    assert result[CONF_CHANGE_FREQUENCY] == 3600


@pytest.mark.parametrize(
    (CONF_CHANGE_FREQUENCY, "expected"),
    [(0, 0.0), ("0", 0.0)],
)
def test_validate_start_service_data_accepts_zero_change_frequency(
    change_frequency: object, expected: float | list[float]
) -> None:
    """Accept scalar zero as the explicit one-shot frequency."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_FREQUENCY] = change_frequency

    result = validate_start_service_data(data)

    assert result[CONF_CHANGE_FREQUENCY] == expected


@pytest.mark.parametrize(
    (CONF_CHANGE_FREQUENCY, "expected"),
    [
        (0.1, 0.1),
        ("0.1", 0.1),
        ((0.1, 1), (0.1, 1.0)),
        ("[0.1, 1]", [0.1, 1.0]),
    ],
)
def test_validate_start_service_data_accepts_safe_repeating_frequency(
    change_frequency: object, expected: float | list[float] | tuple[float, float]
) -> None:
    """Accept repeating values and range bounds beginning at 0.1 seconds."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_FREQUENCY] = change_frequency

    result = validate_start_service_data(data)

    assert result[CONF_CHANGE_FREQUENCY] == expected


@pytest.mark.parametrize(
    CONF_CHANGE_FREQUENCY,
    [0.01, "0.01", (0, 0.1), "[0, 0.1]", (0.01, 0.09), "[0.01, 0.09]"],
)
def test_normalize_scene_input_rejects_unsafe_repeating_frequency(
    change_frequency: object,
) -> None:
    """Reject repeating values or range bounds below 0.1 seconds."""
    data = _base_input()
    data[CONF_CHANGE_FREQUENCY] = change_frequency

    with pytest.raises(vol.Invalid, match="change_frequency_not_int_or_range"):
        normalize_scene_input(data)


@pytest.mark.parametrize(
    CONF_CHANGE_FREQUENCY,
    [0.01, "0.01", (0, 0.1), "[0, 0.1]", (0.01, 0.09), "[0.01, 0.09]"],
)
def test_validate_start_service_data_rejects_unsafe_repeating_frequency(
    change_frequency: object,
) -> None:
    """Reject unsafe repeating frequencies at the runtime service boundary."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_FREQUENCY] = change_frequency

    with pytest.raises(vol.Invalid):
        validate_start_service_data(data)


@pytest.mark.parametrize(
    CONF_BRIGHTNESS,
    [(0.5,), ("0.5",), ([1, 2.5],), ("[1, 2.5]",)],
)
def test_validate_start_service_data_rejects_fractional_brightness(
    brightness: object,
) -> None:
    """Reject fractional brightness values before runtime light calls."""
    data = normalize_scene_input(_base_input())
    data[CONF_BRIGHTNESS] = brightness

    with pytest.raises(vol.Invalid) as err:
        validate_start_service_data(data)
    assert "priority_not_int" not in str(err.value)


@pytest.mark.parametrize(
    CONF_CHANGE_AMOUNT,
    [0.5, "0.5", (1, 2.5), ("1", "2.5")],
)
def test_validate_start_service_data_rejects_fractional_change_amount(
    change_amount: object,
) -> None:
    """Reject fractional scalar and range change amounts without truncation."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_AMOUNT] = change_amount

    with pytest.raises(vol.Invalid) as err:
        validate_start_service_data(data)
    assert "priority_not_int" not in str(err.value)


@pytest.mark.parametrize(
    (CONF_CHANGE_AMOUNT, "expected"),
    [(2.0, 2), ("2.0", 2), ((1.0, "2.0"), (1, 2))],
)
def test_validate_start_service_data_accepts_integral_change_amount(
    change_amount: object, expected: int | list[int]
) -> None:
    """Convert integral float and string change amounts to runtime integers."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_AMOUNT] = change_amount

    result = validate_start_service_data(data)

    assert result[CONF_CHANGE_AMOUNT] == expected


@pytest.mark.parametrize((CONF_PRIORITY, "expected"), [(1.0, 1), ("1.0", 1), ("-2", -2)])
def test_validate_start_service_data_accepts_integral_priority(
    priority: object, expected: int
) -> None:
    """Normalize integral float and numeric-string priorities to integers."""
    data = normalize_scene_input(_base_input())
    data[CONF_PRIORITY] = priority

    result = validate_start_service_data(data)

    assert result[CONF_PRIORITY] == expected


@pytest.mark.parametrize(CONF_PRIORITY, ["high", 1.5, "1.5", -2.5])
def test_validate_start_service_data_rejects_invalid_priority(priority: object) -> None:
    """Reject nonnumeric and fractional priorities at the service boundary."""
    data = normalize_scene_input(_base_input())
    data[CONF_PRIORITY] = priority

    with pytest.raises(vol.Invalid, match="priority_not_int"):
        validate_start_service_data(data)


@pytest.mark.parametrize((CONF_PRIORITY, "expected"), [(1, 1), (1.0, 1), ("-2.0", -2)])
def test_normalize_scene_input_accepts_integral_priority(priority: object, expected: int) -> None:
    """Normalize integral priority forms consistently before manager validation."""
    data = _base_input()
    data[CONF_PRIORITY] = priority

    result = normalize_scene_input(data)

    assert result[CONF_PRIORITY] == expected


@pytest.mark.parametrize(CONF_PRIORITY, [1.5, "1.5", -2.5])
def test_normalize_scene_input_rejects_fractional_priority(priority: object) -> None:
    """Reject fractional priorities before the manager can round them."""
    data = _base_input()
    data[CONF_PRIORITY] = priority

    with pytest.raises(vol.Invalid, match="priority_not_int"):
        normalize_scene_input(data)


@pytest.mark.parametrize(
    CONF_CHANGE_FREQUENCY,
    [
        -1,
        "-1",
        3600.1,
        "3600.1",
    ],
)
def test_validate_start_service_data_rejects_out_of_range_frequency(
    change_frequency: object,
) -> None:
    """Reject frequency service values outside the safe runtime range."""
    data = normalize_scene_input(_base_input())
    data[CONF_CHANGE_FREQUENCY] = change_frequency

    with pytest.raises(vol.Invalid):
        validate_start_service_data(data)


def test_validate_start_service_data_rejects_config_flow_metadata() -> None:
    """Keep runtime service validation strict even when config normalization is permissive."""
    data = normalize_scene_input(_base_input())
    data[CONF_ENTITY_TYPE] = "scene"

    with pytest.raises(vol.Invalid, match="extra keys not allowed"):
        validate_start_service_data(data)


@pytest.mark.parametrize(
    "colors",
    [
        pytest.param([{"color_type": "rgb_color", "color": [255, 0]}], id="malformed"),
        pytest.param([], id="empty"),
    ],
)
def test_validate_start_service_data_rejects_invalid_colors(colors: list[object]) -> None:
    """Reject invalid color lists before animation startup."""
    data = normalize_scene_input(_base_input())
    data[CONF_COLORS] = colors

    with pytest.raises(vol.Invalid):
        validate_start_service_data(data)


def test_validate_start_service_data_rejects_all_zero_color_weights() -> None:
    """Reject color groups that leave random selection with no usable color."""
    data = normalize_scene_input(_base_input())
    data[CONF_COLORS] = [
        {"color_type": "rgb_color", "color": [255, 0, 0], "weight": 0},
        {"color_type": "rgb_color", "color": [0, 0, 255], "weight": 0},
    ]

    with pytest.raises(vol.Invalid, match="colors_malformed"):
        validate_start_service_data(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transition", []),
        ("transition", [1, 2, 3]),
        ("change_frequency", []),
        ("change_frequency", [1, 2, 3]),
        (CONF_CHANGE_AMOUNT, []),
        (CONF_CHANGE_AMOUNT, [1, 2, 3]),
        (CONF_BRIGHTNESS, []),
        (CONF_BRIGHTNESS, [1, 2, 3]),
    ],
)
def test_validate_start_service_data_rejects_malformed_ranges(
    field: str,
    value: list[int],
) -> None:
    """Reject empty and overlong range lists before runtime randomization."""
    data = normalize_scene_input(_base_input())
    data[field] = value

    with pytest.raises(vol.Invalid):
        validate_start_service_data(data)


@pytest.mark.parametrize("brightness", [[], [1, 2, 3]])
def test_validate_start_service_data_rejects_malformed_color_brightness_ranges(
    brightness: list[int],
) -> None:
    """Reject malformed per-color brightness ranges before light updates."""
    data = normalize_scene_input(_base_input())
    data[CONF_COLORS] = [
        {"color_type": "rgb_color", "color": [255, 0, 0], CONF_BRIGHTNESS: brightness}
    ]

    with pytest.raises(vol.Invalid):
        validate_start_service_data(data)


def test_build_colors_from_rgb_dict_converts_to_color_list() -> None:
    """Convert config-flow RGB UI storage into runtime colors."""
    result = build_colors_from_rgb_dict(
        {
            "one": {"color": [1, 2, 3], "brightness": 200, "weight": 10},
            "two": {"color": [4, 5, 6], "brightness": [100, 255], "weight": 5},
        }
    )

    assert result == [
        {"color": [1, 2, 3], "brightness": 200, "weight": 10, "color_type": CONF_COLOR_RGB},
        {
            "color": [4, 5, 6],
            "brightness": [100, 255],
            "weight": 5,
            "color_type": CONF_COLOR_RGB,
        },
    ]


def test_clean_color_rgb_dict_copies_only_retained_color_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean RGB UI data without deep-copying the whole color mapping."""
    color_rgb_dict = {
        "keep": {"color": [1, 2, 3], "color_delete_color": False},
        "delete": {"color": [4, 5, 6], "color_delete_color": True},
    }
    copied_objects: list[object] = []
    original_deepcopy = scene_config.copy.deepcopy

    def track_deepcopy(value: object) -> object:
        """Track copied objects while preserving deepcopy behavior."""
        copied_objects.append(value)
        return original_deepcopy(value)

    monkeypatch.setattr(scene_config.copy, "deepcopy", track_deepcopy)

    result = clean_color_rgb_dict(color_rgb_dict)

    assert result == {"keep": {"color": [1, 2, 3]}}
    assert color_rgb_dict == {
        "keep": {"color": [1, 2, 3], "color_delete_color": False},
        "delete": {"color": [4, 5, 6], "color_delete_color": True},
    }
    assert color_rgb_dict not in copied_objects


def test_build_colors_from_rgb_dict_copies_only_color_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build runtime colors without deep-copying the whole color mapping."""
    color_rgb_dict = {
        "one": {"color": [1, 2, 3], "brightness": 200, "weight": 10},
        "two": {"color": [4, 5, 6], "brightness": [100, 255], "weight": 5},
    }
    copied_objects: list[object] = []
    original_deepcopy = scene_config.copy.deepcopy

    def track_deepcopy(value: object) -> object:
        """Track copied objects while preserving deepcopy behavior."""
        copied_objects.append(value)
        return original_deepcopy(value)

    monkeypatch.setattr(scene_config.copy, "deepcopy", track_deepcopy)

    result = build_colors_from_rgb_dict(color_rgb_dict)

    assert result == [
        {"color": [1, 2, 3], "brightness": 200, "weight": 10, "color_type": CONF_COLOR_RGB},
        {
            "color": [4, 5, 6],
            "brightness": [100, 255],
            "weight": 5,
            "color_type": CONF_COLOR_RGB,
        },
    ]
    assert color_rgb_dict == {
        "one": {"color": [1, 2, 3], "brightness": 200, "weight": 10},
        "two": {"color": [4, 5, 6], "brightness": [100, 255], "weight": 5},
    }
    assert color_rgb_dict not in copied_objects
