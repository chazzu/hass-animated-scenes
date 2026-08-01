"""Tests for Animated Scenes config and options flows."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_BRIGHTNESS, CONF_LIGHTS, CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.animations import Animation, Animations
from custom_components.animated_scenes.config_flow import (
    AnimatedScenesConfigFlow,
    AnimatedScenesOptionsFlowHandler,
)
from custom_components.animated_scenes.const import (
    ABORT_ACTIVITY_SENSOR_EXISTS,
    COLOR_SELECTOR_RGB_UI,
    COLOR_SELECTOR_YAML,
    CONF_COLOR,
    CONF_COLOR_DELETE_COLOR,
    CONF_COLOR_NEARBY_COLORS,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_COLOR_WEIGHT,
    CONF_COLORS,
    CONF_ENTITY_TYPE,
    CONF_PLATFORM,
    CONF_TRANSITION,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_NEARBY_COLORS,
    DEFAULT_COLOR_WEIGHT,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    ENTITY_SCENE,
    ERROR_BRIGHTNESS_NOT_INT_OR_RANGE,
    ERROR_COLORS_IS_BLANK,
    ERROR_COLORS_MALFORMED,
    ERROR_SCENE_NAME_EXISTS,
)
from custom_components.animated_scenes.scene_config import (
    build_colors_from_rgb_dict,
    validate_start_service_data,
)


def _schema_has_key(data_schema: object, key: str) -> bool:
    """Return whether a voluptuous schema includes a top-level key."""
    schema = getattr(data_schema, "schema", {})
    return any(getattr(marker, "schema", marker) == key for marker in schema)


def _options_flow(
    hass: HomeAssistant,
    *,
    selector_mode: str = COLOR_SELECTOR_YAML,
    color_rgb_dict: dict[str, dict[str, object]] | None = None,
) -> tuple[AnimatedScenesOptionsFlowHandler, MockConfigEntry]:
    """Return an options flow and its backing scene config entry."""
    data: dict[str, object] = {
        CONF_NAME: "Spooky",
        CONF_ENTITY_TYPE: ENTITY_SCENE,
        CONF_COLOR_SELECTOR_MODE: selector_mode,
        CONF_LIGHTS: ["light.one"],
        CONF_TRANSITION: 1,
    }
    if selector_mode == COLOR_SELECTOR_RGB_UI:
        data[CONF_COLOR_RGB_DICT] = color_rgb_dict or {}
    else:
        data.update(
            {
                "change_frequency": 1,
                "change_amount": "all",
                "brightness": 255,
            }
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Spooky",
        data=data,
        entry_id="spooky",
    )
    entry.add_to_hass(hass)
    flow = AnimatedScenesOptionsFlowHandler(entry)
    flow.hass = hass
    return flow, entry


def _scene_input(name: str) -> dict[str, object]:
    """Return valid scene-step input using the YAML color path."""
    return {
        CONF_NAME: name,
        CONF_LIGHTS: ["light.one"],
        CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_YAML,
    }


def _existing_scene(hass: HomeAssistant, name: str, entry_id: str) -> MockConfigEntry:
    """Add and return an existing scene config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=name,
        data={CONF_NAME: name, CONF_ENTITY_TYPE: ENTITY_SCENE},
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    return entry


async def test_stale_activity_sensor_menu_aborts_after_competing_creation(
    hass: HomeAssistant,
) -> None:
    """Recheck activity-sensor uniqueness after a stale menu selection."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    menu = await flow.async_step_user()
    competing_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Activity Sensor",
        data={CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR},
        entry_id="activity",
    )
    competing_entry.add_to_hass(hass)
    result = await flow.async_step_activity_sensor()

    assert menu["type"] == "menu"
    assert result["type"] == "abort"
    assert result["reason"] == ABORT_ACTIVITY_SENSOR_EXISTS
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_scene_creation_rejects_duplicate_name(hass: HomeAssistant) -> None:
    """Reject a UI-created scene whose runtime name is already in use."""
    _existing_scene(hass, "Spooky", "existing")
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    result = await flow.async_step_scene(_scene_input("Spooky"))

    assert result["type"] == "form"
    assert result["step_id"] == "scene"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}


async def test_scene_import_rejects_duplicate_name(hass: HomeAssistant) -> None:
    """Reject an imported scene whose runtime name is already in use."""
    _existing_scene(hass, "Spooky", "existing")
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    result = await flow.async_step_import(_scene_input("Spooky"))

    assert result["type"] == "form"
    assert result["step_id"] == "scene"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}


async def test_yaml_creation_rechecks_duplicate_name_before_create(
    hass: HomeAssistant,
) -> None:
    """Reject a competing scene created after the YAML scene step."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    scene_result = await flow.async_step_scene(_scene_input("Spooky"))
    _existing_scene(hass, "Spooky", "competing")

    result = await flow.async_step_color_yaml(
        {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
    )

    assert scene_result["step_id"] == "color_yaml"
    assert result["type"] == "form"
    assert result["step_id"] == "color_yaml"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_rgb_creation_rechecks_duplicate_name_before_create(
    hass: HomeAssistant,
) -> None:
    """Reject a competing scene created after the RGB scene step."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    scene_input = _scene_input("Spooky")
    scene_input[CONF_COLOR_SELECTOR_MODE] = COLOR_SELECTOR_RGB_UI
    scene_result = await flow.async_step_scene(scene_input)
    _existing_scene(hass, "Spooky", "competing")

    result = await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0]})

    assert scene_result["step_id"] == "color_rgb_ui"
    assert result["type"] == "form"
    assert result["step_id"] == "color_rgb_ui"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_options_rename_rejects_duplicate_name(hass: HomeAssistant) -> None:
    """Reject renaming a scene to another entry's runtime name."""
    flow, entry = _options_flow(hass)
    _existing_scene(hass, "Scary", "other")

    result = await flow.async_step_scene({CONF_NAME: "Scary"})

    assert result["type"] == "form"
    assert result["step_id"] == "scene"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}
    assert entry.data[CONF_NAME] == "Spooky"


async def test_options_rename_rechecks_duplicate_name_before_update(
    hass: HomeAssistant,
) -> None:
    """Reject a competing scene created after the options scene step."""
    flow, entry = _options_flow(hass)
    scene_result = await flow.async_step_scene({CONF_NAME: "Scary"})
    _existing_scene(hass, "Scary", "competing")

    with (
        patch.object(hass.config_entries, "async_update_entry") as update_entry,
        patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry,
    ):
        result = await flow.async_step_color_yaml(
            {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
        )

    assert scene_result["step_id"] == "color_yaml"
    assert result["type"] == "form"
    assert result["step_id"] == "color_yaml"
    assert result["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}
    update_entry.assert_not_called()
    reload_entry.assert_not_awaited()
    assert entry.data[CONF_NAME] == "Spooky"


async def test_options_rgb_ui_handles_empty_existing_color_dict(hass: HomeAssistant) -> None:
    """Show the first RGB color form when stored color data is empty.

    Args:
        hass: Home Assistant test instance.

    """
    flow, _ = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)

    result = await flow.async_step_color_rgb_ui()

    assert result["type"] == "form"
    assert result["step_id"] == "color_rgb_ui"


async def test_new_rgb_ui_rejects_missing_color(hass: HomeAssistant) -> None:
    """Reject a new RGB UI color submission without a selected color."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    result = await flow.async_step_color_rgb_ui({CONF_BRIGHTNESS: 100})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_IS_BLANK}


async def test_new_rgb_ui_rejects_all_zero_color_weights(hass: HomeAssistant) -> None:
    """Reject a completed new RGB scene with no selectable color weight."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    await flow.async_step_scene(
        {
            CONF_NAME: "Zero Weight",
            CONF_LIGHTS: ["light.one"],
            CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_RGB_UI,
        }
    )

    result = await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0], CONF_COLOR_WEIGHT: 0})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_MALFORMED}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_options_rgb_ui_rejects_missing_color(hass: HomeAssistant) -> None:
    """Reject an options RGB UI submission whose color is missing."""
    flow, entry = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)

    result = await flow.async_step_color_rgb_ui({CONF_BRIGHTNESS: 100})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_IS_BLANK}
    assert entry.data[CONF_COLOR_RGB_DICT] == {}


async def test_options_rgb_ui_rejects_all_zero_color_weights(hass: HomeAssistant) -> None:
    """Reject zero-total RGB options without updating or reloading the entry."""
    flow, entry = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)

    with (
        patch.object(hass.config_entries, "async_update_entry") as update_entry,
        patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry,
    ):
        result = await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0], CONF_COLOR_WEIGHT: 0})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_MALFORMED}
    update_entry.assert_not_called()
    reload_entry.assert_not_awaited()
    assert entry.data[CONF_COLOR_RGB_DICT] == {}


async def test_options_scene_form_exposes_name_for_rename(hass: HomeAssistant) -> None:
    """Expose the scene name in options so users can submit renames."""
    flow, _ = _options_flow(hass)

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert _schema_has_key(result["data_schema"], CONF_NAME)


async def test_legacy_scene_without_entity_type_has_options(hass: HomeAssistant) -> None:
    """Treat legacy options data without entity type as a scene."""
    flow, _ = _options_flow(hass)
    flow._data.pop(CONF_ENTITY_TYPE)

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "scene"


async def test_options_rgb_ui_defaults_missing_optional_color_values(
    hass: HomeAssistant,
) -> None:
    """Apply optional RGB UI color defaults before rounding submitted values."""
    flow, entry = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0]})

    assert result["type"] == "create_entry"
    color_data = next(iter(entry.data[CONF_COLOR_RGB_DICT].values()))
    assert color_data[CONF_BRIGHTNESS] == DEFAULT_BRIGHTNESS
    assert color_data[CONF_COLOR_WEIGHT] == DEFAULT_COLOR_WEIGHT
    assert color_data[CONF_COLOR_NEARBY_COLORS] == DEFAULT_COLOR_NEARBY_COLORS


async def test_options_rgb_ui_adds_color_when_stored_color_dict_is_missing(
    hass: HomeAssistant,
) -> None:
    """Persist RGB UI color data when a legacy entry lacks the color dict."""
    flow, entry = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)
    flow._data.pop(CONF_COLOR_RGB_DICT)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0]})

    assert result["type"] == "create_entry"
    assert len(entry.data[CONF_COLOR_RGB_DICT]) == 1
    color_data = next(iter(entry.data[CONF_COLOR_RGB_DICT].values()))
    assert color_data[CONF_BRIGHTNESS] == DEFAULT_BRIGHTNESS

    runtime_data = dict(entry.data)
    runtime_data[CONF_COLORS] = build_colors_from_rgb_dict(entry.data[CONF_COLOR_RGB_DICT])
    runtime_data.pop(CONF_COLOR_RGB_DICT)
    runtime_data.pop(CONF_COLOR_SELECTOR_MODE)
    runtime_data.pop(CONF_ENTITY_TYPE)
    validate_start_service_data(runtime_data)


async def test_options_rgb_ui_invalid_edit_does_not_mutate_entry_data(
    hass: HomeAssistant,
) -> None:
    """Validate edited RGB UI color data without aliasing config entry data."""
    stored_color = {
        CONF_COLOR: [255, 0, 0],
        CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
        CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
        CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
    }
    flow, entry = _options_flow(
        hass,
        selector_mode=COLOR_SELECTOR_RGB_UI,
        color_rgb_dict={"red": stored_color},
    )

    result = await flow.async_step_color_rgb_ui({CONF_BRIGHTNESS: "invalid"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_BRIGHTNESS_NOT_INT_OR_RANGE}
    assert entry.data[CONF_COLOR_RGB_DICT] == {"red": stored_color}


async def test_options_rgb_ui_rejects_deleting_only_color(
    hass: HomeAssistant,
) -> None:
    """Reject options edits that would leave an RGB UI scene with no colors."""
    stored_color = {
        CONF_COLOR: [255, 0, 0],
        CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
        CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
        CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
    }
    flow, entry = _options_flow(
        hass,
        selector_mode=COLOR_SELECTOR_RGB_UI,
        color_rgb_dict={"red": stored_color},
    )

    result = await flow.async_step_color_rgb_ui(
        {
            **stored_color,
            CONF_COLOR_DELETE_COLOR: True,
        }
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_IS_BLANK}
    assert entry.data[CONF_COLOR_RGB_DICT] == {"red": stored_color}


async def test_options_rename_stops_previous_animation_before_reload(
    hass: HomeAssistant,
) -> None:
    """Stop an active pre-rename animation before options update entry data."""
    manager = Animations(hass)
    manager.animations["Spooky"] = cast("Animation", AsyncMock())
    Animations.instance = manager
    flow, entry = _options_flow(hass)

    with (
        patch.object(manager, "stop_by_name", AsyncMock()) as stop_by_name,
        patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry,
    ):
        scene_result = await flow.async_step_scene({CONF_NAME: "Scary"})
        result = await flow.async_step_color_yaml(
            {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
        )

    assert scene_result["type"] == "form"
    assert scene_result["step_id"] == "color_yaml"
    stop_by_name.assert_awaited_once_with("Spooky")
    reload_entry.assert_awaited_once_with("spooky")
    assert entry.title == "Scary"
    assert entry.data[CONF_NAME] == "Scary"
    assert result["type"] == "create_entry"


async def test_options_yaml_accepts_imported_legacy_platform(
    hass: HomeAssistant,
) -> None:
    """Ignore legacy YAML platform metadata during runtime validation."""
    flow, entry = _options_flow(hass)
    flow._data[CONF_PLATFORM] = DOMAIN

    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await flow.async_step_color_yaml(
            {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
        )

    assert result["type"] == "create_entry"
    assert entry.data[CONF_PLATFORM] == DOMAIN


@pytest.mark.parametrize(
    ("colors", "expected_error"),
    [
        pytest.param([], ERROR_COLORS_IS_BLANK, id="empty"),
        pytest.param(
            [{"color_type": "rgb_color", "color": [255, 0]}],
            ERROR_COLORS_MALFORMED,
            id="malformed",
        ),
    ],
)
async def test_options_yaml_rejects_invalid_colors(
    hass: HomeAssistant, colors: list[object], expected_error: str
) -> None:
    """Reject invalid YAML colors before saving options."""
    flow, _ = _options_flow(hass)

    result = await flow.async_step_color_yaml({CONF_COLORS: colors})

    assert result["type"] == "form"
    errors = result["errors"]
    assert errors is not None
    assert errors["base"] == expected_error


async def test_options_yaml_logs_runtime_validation_error(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Leave a debug trail when runtime schema rejects YAML colors."""
    flow, _ = _options_flow(hass)
    caplog.set_level(logging.DEBUG, "custom_components.animated_scenes.config_flow")

    result = await flow.async_step_color_yaml(
        {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0]}]}
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_MALFORMED}
    assert "Invalid YAML color payload" in caplog.text
