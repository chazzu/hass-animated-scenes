"""Tests for Animated Scenes config and options flows."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlowResult
from homeassistant.const import CONF_BRIGHTNESS, CONF_LIGHTS, CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.config_flow import (
    AnimatedScenesConfigFlow,
    AnimatedScenesOptionsFlowHandler,
)
from custom_components.animated_scenes.const import (
    ABORT_ACTIVITY_SENSOR_EXISTS,
    ABORT_IMPORT_INVALID,
    ABORT_IMPORT_SCENE_NAME_EXISTS,
    COLOR_SELECTOR_RGB_UI,
    COLOR_SELECTOR_YAML,
    CONF_COLOR,
    CONF_COLOR_ADD_COLOR,
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
    ERROR_PRIORITY_NOT_INT,
    ERROR_SCENE_NAME_BLANK,
    ERROR_SCENE_NAME_EXISTS,
    PRIORITY_MAX,
    PRIORITY_MIN,
)
from custom_components.animated_scenes.scene_config import (
    build_colors_from_rgb_dict,
    validate_start_service_data,
)
from custom_components.animated_scenes.switch import PLATFORM_SCHEMA

from .helpers import animation_tasks, register_light_services

TRANSLATIONS_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "animated_scenes"
    / "translations"
    / "en.json"
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
    omit: tuple[str, ...] = (),
    extra: dict[str, object] | None = None,
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
    data.update(extra or {})
    for key in omit:
        data.pop(key, None)
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


async def test_scene_creation_strips_name_and_rejects_padded_duplicate(
    hass: HomeAssistant,
) -> None:
    """Store a stripped name and reject a padded copy of an existing scene."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "scene"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _scene_input("  Foo ")
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COLORS: [{"color_type": "rgb_color", "color": [1, 2, 3]}]}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Foo"
    assert [entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)] == ["Foo"]

    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    duplicate = await flow.async_step_scene(_scene_input(" Foo"))

    assert duplicate["errors"] == {"base": ERROR_SCENE_NAME_EXISTS}


def _yaml_scene(name: str = "Spooky", **overrides: object) -> dict[str, object]:
    """Return a legacy YAML scene validated by the switch platform schema."""
    return PLATFORM_SCHEMA(
        {
            CONF_PLATFORM: DOMAIN,
            CONF_NAME: name,
            CONF_LIGHTS: ["light.one"],
            CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
            **overrides,
        }
    )


async def _import_yaml_scene(hass: HomeAssistant, config: dict[str, object]) -> ConfigFlowResult:
    """Run a YAML import flow through the flow manager and wait for setup."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=config
    )
    await hass.async_block_till_done()
    return result


async def test_yaml_import_creates_scene_entry(hass: HomeAssistant) -> None:
    """Import a YAML scene as a YAML-color entry keyed by its YAML name."""
    result = await _import_yaml_scene(hass, _yaml_scene())

    assert result["type"] == "create_entry"
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].title == "Spooky"
    assert entries[0].unique_id == "Spooky"
    assert entries[0].data[CONF_NAME] == "Spooky"
    assert entries[0].data[CONF_COLOR_SELECTOR_MODE] == COLOR_SELECTOR_YAML
    assert entries[0].data[CONF_ENTITY_TYPE] == ENTITY_SCENE
    assert hass.config_entries.flow.async_progress() == []


async def test_yaml_import_strips_scene_name(hass: HomeAssistant) -> None:
    """Store an imported scene under its stripped name."""
    result = await _import_yaml_scene(hass, _yaml_scene(" Foo "))

    assert result["type"] == "create_entry"
    assert result["title"] == "Foo"
    assert hass.config_entries.async_entries(DOMAIN)[0].data[CONF_NAME] == "Foo"


@pytest.mark.parametrize(
    ("name", "overrides", "existing_name", "reason"),
    [
        ("Spooky", {}, "Spooky", ABORT_IMPORT_SCENE_NAME_EXISTS),
        ("Spooky", {CONF_TRANSITION: 99999}, None, ABORT_IMPORT_INVALID),
        ("Spooky", {"priority": 10**20}, None, ABORT_IMPORT_INVALID),
        ("   ", {}, None, ABORT_IMPORT_INVALID),
    ],
    ids=["duplicate_name", "invalid_transition", "huge_priority", "blank_name"],
)
async def test_yaml_import_aborts_when_scene_cannot_be_imported(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    name: str,
    overrides: dict[str, object],
    existing_name: str | None,
    reason: str,
) -> None:
    """End a rejected import with a logged abort instead of a pending form."""
    if existing_name is not None:
        _existing_scene(hass, existing_name, "existing")
    config = {
        CONF_PLATFORM: DOMAIN,
        CONF_NAME: name,
        CONF_LIGHTS: ["light.one"],
        CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
        **overrides,
    }

    with caplog.at_level(logging.WARNING):
        result = await _import_yaml_scene(hass, config)

    assert result["type"] == "abort"
    assert result["reason"] == reason
    assert hass.config_entries.flow.async_progress() == []
    assert len(hass.config_entries.async_entries(DOMAIN)) == (1 if existing_name else 0)
    assert "Not importing YAML animated scene" in caplog.text


async def test_yaml_import_aborts_when_scene_was_already_imported(hass: HomeAssistant) -> None:
    """Keep a renamed imported scene from being imported again under its YAML name."""
    MockConfigEntry(
        domain=DOMAIN,
        title="Renamed",
        unique_id="Spooky",
        source=SOURCE_IMPORT,
        data={CONF_NAME: "Renamed", CONF_ENTITY_TYPE: ENTITY_SCENE},
    ).add_to_hass(hass)

    result = await _import_yaml_scene(hass, _yaml_scene())

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_yaml_import_without_config_aborts(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Abort an import flow started without YAML data instead of crashing."""
    with caplog.at_level(logging.WARNING):
        result = await _import_yaml_scene(hass, None)  # type: ignore[arg-type]

    assert result["type"] == "abort"
    assert result["reason"] == ABORT_IMPORT_INVALID
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert "no configuration was given" in caplog.text


def test_import_abort_reasons_have_translations() -> None:
    """Give every import abort reason user-facing text."""
    translations = json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8"))

    assert {
        ABORT_IMPORT_INVALID,
        ABORT_IMPORT_SCENE_NAME_EXISTS,
        "already_configured",
        "already_in_progress",
    } <= set(translations["config"]["abort"])


async def test_user_menu_creates_activity_sensor(hass: HomeAssistant) -> None:
    """Offer the activity sensor in the user menu and create it when chosen."""
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert menu["type"] == "menu"
    assert menu["menu_options"] == ["activity_sensor", "scene"]

    result = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "activity_sensor"}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["title"] == "Activity Sensor"
    entries = hass.config_entries.async_entries(DOMAIN)
    assert [entry.data[CONF_ENTITY_TYPE] for entry in entries] == [ENTITY_ACTIVITY_SENSOR]


@pytest.mark.parametrize("priority", [PRIORITY_MAX + 1, 1e20], ids=["just_over", "huge"])
async def test_scene_flows_reject_out_of_range_priority(
    hass: HomeAssistant, priority: float
) -> None:
    """Show the priority error and keep an unstorable priority out of the entry."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    options_flow, entry = _options_flow(hass, extra={"priority": 5})

    config_result = await flow.async_step_scene({**_scene_input("Scary"), "priority": priority})
    options_result = await options_flow.async_step_scene(
        {CONF_NAME: "Spooky", "priority": priority}
    )

    for result in (config_result, options_result):
        assert result["type"] == "form"
        assert result["step_id"] == "scene"
        assert result["errors"] == {"base": ERROR_PRIORITY_NOT_INT}
    assert entry.data["priority"] == 5
    assert [item.entry_id for item in hass.config_entries.async_entries(DOMAIN)] == ["spooky"]


async def test_scene_flow_stores_priority_at_range_limit_as_int(hass: HomeAssistant) -> None:
    """Store the lowest documented priority as an integer, not an equal float."""
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    scene_form = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "scene"}
    )
    color_form = await hass.config_entries.flow.async_configure(
        scene_form["flow_id"], {**_scene_input("Scary"), "priority": float(PRIORITY_MIN)}
    )
    assert color_form["step_id"] == "color_yaml"

    result = await hass.config_entries.flow.async_configure(
        color_form["flow_id"],
        {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]},
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    stored_priority = result["result"].data["priority"]
    assert type(stored_priority) is int
    assert stored_priority == PRIORITY_MIN


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


@pytest.mark.parametrize(
    ("source", "unique_id", "other_unique_id", "expected_unique_id"),
    [
        (SOURCE_IMPORT, None, None, "Spooky"),
        ("user", None, None, None),
        (SOURCE_IMPORT, "Original", None, "Original"),
        (SOURCE_IMPORT, None, "Spooky", None),
    ],
    ids=["legacy_import", "ui_created", "import_with_yaml_name", "yaml_name_taken"],
)
async def test_options_rename_records_yaml_name_only_for_legacy_import(
    hass: HomeAssistant,
    source: str,
    unique_id: str | None,
    other_unique_id: str | None,
    expected_unique_id: str | None,
) -> None:
    """Record the old title as the YAML name only for an older imported entry.

    A UI-created scene has no YAML scene to protect, an imported entry that
    already records its YAML name keeps it, and a name another entry already
    holds as its unique id is left alone so the rename still saves.
    """
    if other_unique_id is not None:
        MockConfigEntry(
            domain=DOMAIN,
            title="Other",
            unique_id=other_unique_id,
            source=SOURCE_IMPORT,
            data={CONF_NAME: "Other", CONF_ENTITY_TYPE: ENTITY_SCENE},
        ).add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Spooky",
        source=source,
        unique_id=unique_id,
        data={
            CONF_NAME: "Spooky",
            CONF_ENTITY_TYPE: ENTITY_SCENE,
            CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_YAML,
            CONF_LIGHTS: ["light.one"],
        },
    )
    entry.add_to_hass(hass)
    flow = AnimatedScenesOptionsFlowHandler(entry)
    flow.hass = hass

    await flow.async_step_scene({CONF_NAME: "Scary"})
    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await flow.async_step_color_yaml(
            {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
        )

    assert result["type"] == "create_entry"
    assert entry.title == "Scary"
    assert entry.data[CONF_NAME] == "Scary"
    assert entry.unique_id == expected_unique_id
    others = [item for item in hass.config_entries.async_entries(DOMAIN) if item is not entry]
    assert [item.unique_id for item in others] == ([other_unique_id] if other_unique_id else [])


async def test_options_rgb_ui_counts_added_colors(hass: HomeAssistant) -> None:
    """Count an added color in the total instead of showing "Color #2 of 1"."""
    flow, _ = _options_flow(
        hass,
        selector_mode=COLOR_SELECTOR_RGB_UI,
        color_rgb_dict={"one": {CONF_COLOR: [255, 0, 0]}},
    )

    first = await flow.async_step_color_rgb_ui()
    second = await flow.async_step_color_rgb_ui(
        {CONF_COLOR: [255, 0, 0], CONF_COLOR_ADD_COLOR: True}
    )

    assert first["description_placeholders"] is not None
    assert first["description_placeholders"]["color_count"] == "1"
    assert first["description_placeholders"]["color_max"] == "1"
    assert second["type"] == "form"
    assert second["description_placeholders"] is not None
    assert second["description_placeholders"]["color_count"] == "2"
    assert second["description_placeholders"]["color_max"] == "2"


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


# The selectors' max bounds already reject infinity, but NaN passes them.
NON_FINITE_COLOR_NUMBERS = [
    pytest.param(CONF_COLOR_WEIGHT, float("nan"), id="weight_nan"),
    pytest.param(CONF_COLOR_NEARBY_COLORS, float("nan"), id="nearby_colors_nan"),
]


@pytest.mark.parametrize(("field", "value"), NON_FINITE_COLOR_NUMBERS)
async def test_new_rgb_ui_rejects_non_finite_color_numbers(
    hass: HomeAssistant, field: str, value: float
) -> None:
    """Show the malformed-colors error for NaN instead of crashing."""
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    scene_form = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "scene"}
    )
    color_form = await hass.config_entries.flow.async_configure(
        scene_form["flow_id"],
        {
            CONF_NAME: "Not A Number",
            CONF_LIGHTS: ["light.one"],
            CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_RGB_UI,
        },
    )
    assert color_form["step_id"] == "color_rgb_ui"

    result = await hass.config_entries.flow.async_configure(
        color_form["flow_id"], {CONF_COLOR: [255, 0, 0], field: value}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "color_rgb_ui"
    assert result["errors"] == {"base": ERROR_COLORS_MALFORMED}
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(("field", "value"), NON_FINITE_COLOR_NUMBERS)
async def test_options_rgb_ui_rejects_non_finite_color_numbers(
    hass: HomeAssistant, field: str, value: float
) -> None:
    """Keep the stored colors when an options edit sends NaN."""
    stored_color = {
        CONF_COLOR: [255, 0, 0],
        CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
        CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
        CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
    }
    _, entry = _options_flow(
        hass, selector_mode=COLOR_SELECTOR_RGB_UI, color_rgb_dict={"red": stored_color}
    )
    expected_data = copy.deepcopy(dict(entry.data))
    scene_form = await hass.config_entries.options.async_init(entry.entry_id)
    color_form = await hass.config_entries.options.async_configure(
        scene_form["flow_id"], {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.one"]}
    )
    assert color_form["step_id"] == "color_rgb_ui"

    result = await hass.config_entries.options.async_configure(
        color_form["flow_id"], {CONF_COLOR: [255, 0, 0], field: value}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "color_rgb_ui"
    assert result["errors"] == {"base": ERROR_COLORS_MALFORMED}
    assert dict(entry.data) == expected_data


async def test_new_rgb_ui_retry_does_not_store_rejected_color(hass: HomeAssistant) -> None:
    """Keep only the corrected color after a rejected final submission."""
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass
    await flow.async_step_scene(
        {
            CONF_NAME: "Retry",
            CONF_LIGHTS: ["light.one"],
            CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_RGB_UI,
        }
    )
    await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0], CONF_COLOR_WEIGHT: 0})

    result = await flow.async_step_color_rgb_ui({CONF_COLOR: [0, 255, 0], CONF_COLOR_WEIGHT: 10})

    assert result["type"] == "create_entry"
    stored = list(result["data"][CONF_COLOR_RGB_DICT].values())
    assert [color[CONF_COLOR] for color in stored] == [[0, 255, 0]]


async def test_options_rgb_ui_retry_does_not_store_rejected_color(hass: HomeAssistant) -> None:
    """Keep only the corrected new color after an options validation error."""
    flow, entry = _options_flow(hass, selector_mode=COLOR_SELECTOR_RGB_UI)
    await flow.async_step_color_rgb_ui({CONF_COLOR: [255, 0, 0], CONF_COLOR_WEIGHT: 0})

    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await flow.async_step_color_rgb_ui(
            {CONF_COLOR: [0, 255, 0], CONF_COLOR_WEIGHT: 10}
        )

    assert result["type"] == "create_entry"
    stored = list(entry.data[CONF_COLOR_RGB_DICT].values())
    assert [color[CONF_COLOR] for color in stored] == [[0, 255, 0]]


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "whitespace"])
async def test_scene_flows_reject_blank_names(hass: HomeAssistant, name: str) -> None:
    """Reject blank names in both the create and options flows."""
    create_flow = AnimatedScenesConfigFlow()
    create_flow.hass = hass
    options_flow, _ = _options_flow(hass)

    results = [
        await create_flow.async_step_scene(_scene_input(name)),
        await options_flow.async_step_scene(_scene_input(name)),
    ]

    assert [result["errors"] for result in results] == [{"base": ERROR_SCENE_NAME_BLANK}] * 2


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
    flow, _ = _options_flow(hass, omit=(CONF_ENTITY_TYPE,))

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
    flow, entry = _options_flow(
        hass, selector_mode=COLOR_SELECTOR_RGB_UI, omit=(CONF_COLOR_RGB_DICT,)
    )

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
    expected_colors = copy.deepcopy(entry.data[CONF_COLOR_RGB_DICT])

    result = await flow.async_step_color_rgb_ui({CONF_BRIGHTNESS: "invalid"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_BRIGHTNESS_NOT_INT_OR_RANGE}
    assert entry.data[CONF_COLOR_RGB_DICT] == expected_colors


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
    expected_colors = copy.deepcopy(entry.data[CONF_COLOR_RGB_DICT])

    result = await flow.async_step_color_rgb_ui(
        {
            **stored_color,
            CONF_COLOR_DELETE_COLOR: True,
        }
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": ERROR_COLORS_IS_BLANK}
    assert entry.data[CONF_COLOR_RGB_DICT] == expected_colors


async def test_options_rename_stops_previous_animation_before_reload(
    hass: HomeAssistant,
) -> None:
    """Stop an active pre-rename animation before options update entry data."""
    manager = Animations(hass)
    Animations.instance = manager
    register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    await manager.start(
        {
            CONF_NAME: "Spooky",
            CONF_LIGHTS: ["light.one"],
            CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
            "change_frequency": 60,
        }
    )
    flow, entry = _options_flow(hass)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry:
        scene_result = await flow.async_step_scene({CONF_NAME: "Scary"})
        result = await flow.async_step_color_yaml(
            {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
        )

    assert scene_result["type"] == "form"
    assert scene_result["step_id"] == "color_yaml"
    assert manager.animations == {}
    assert animation_tasks("Spooky") == []
    reload_entry.assert_awaited_once_with("spooky")
    assert entry.title == "Scary"
    assert entry.data[CONF_NAME] == "Scary"
    assert result["type"] == "create_entry"


async def _setup_real_scene_entry(hass: HomeAssistant, **overrides: object) -> MockConfigEntry:
    """Set up a real YAML-color scene entry named Spooky and return it."""
    data: dict[str, object] = {
        CONF_NAME: "Spooky",
        CONF_ENTITY_TYPE: ENTITY_SCENE,
        CONF_COLOR_SELECTOR_MODE: COLOR_SELECTOR_YAML,
        CONF_COLOR_RGB_DICT: {},
        "icon": "mdi:lightbulb",
        CONF_LIGHTS: ["light.one"],
        CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}],
        "change_frequency": 3600,
        "change_amount": "all",
        "brightness": 255,
        CONF_TRANSITION: 1,
        **overrides,
    }
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Spooky", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_options_rename_keeps_unrelated_service_animation_with_new_name(
    hass: HomeAssistant,
) -> None:
    """Keep a service animation named like a scene's new name running through reload."""
    register_light_services(hass)
    for light in ("light.one", "light.two"):
        hass.states.async_set(light, "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    entry = await _setup_real_scene_entry(hass)
    manager = Animations.instance
    assert manager is not None
    await hass.services.async_call(
        DOMAIN,
        "start_animation",
        {
            CONF_NAME: "Scary",
            CONF_LIGHTS: ["light.two"],
            CONF_COLORS: [{"color_type": "rgb_color", "color": [0, 255, 0]}],
            "change_frequency": 3600,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(animation_tasks("Scary")) == 1

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_NAME: "Scary", CONF_LIGHTS: ["light.one"]}
    )
    assert flow["step_id"] == "color_yaml"
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.data[CONF_NAME] == "Scary"
    assert "Scary" in manager.animations
    assert len(animation_tasks("Scary")) == 1
    await manager.stop({CONF_NAME: "Scary"})


async def test_options_keep_stored_decimal_timings_when_fields_are_omitted(
    hass: HomeAssistant,
) -> None:
    """Show stored decimal frequency and transition as text defaults and save them unchanged."""
    register_light_services(hass)
    hass.states.async_set("light.one", "on", {"color_mode": "rgb", "rgb_color": (1, 2, 3)})
    entry = await _setup_real_scene_entry(hass, change_frequency=0.5, **{CONF_TRANSITION: 0.5})

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_NAME: "Spooky", CONF_LIGHTS: ["light.one"]}
    )
    assert flow["step_id"] == "color_yaml"
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_COLORS: [{"color_type": "rgb_color", "color": [255, 0, 0]}]}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert entry.data["change_frequency"] == 0.5
    assert entry.data[CONF_TRANSITION] == 0.5
    manager = Animations.instance
    assert manager is not None
    await manager.stop({CONF_NAME: "Spooky"})


async def test_options_yaml_accepts_imported_legacy_platform(
    hass: HomeAssistant,
) -> None:
    """Ignore legacy YAML platform metadata during runtime validation."""
    flow, entry = _options_flow(hass, extra={CONF_PLATFORM: DOMAIN})

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
        pytest.param(
            [{"color_type": "color_temp", "color": float("inf")}],
            ERROR_COLORS_MALFORMED,
            id="color_temp_inf",
        ),
        pytest.param(
            [{"color_type": "color_temp", "color": float("-inf")}],
            ERROR_COLORS_MALFORMED,
            id="color_temp_neg_inf",
        ),
        pytest.param(
            [{"color_type": "color_temp_kelvin", "color": float("inf")}],
            ERROR_COLORS_MALFORMED,
            id="color_temp_kelvin_float_inf",
        ),
        pytest.param(
            [{"color_type": "color_temp_kelvin", "color": "inf"}],
            ERROR_COLORS_MALFORMED,
            id="color_temp_kelvin_inf",
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


async def test_activity_sensor_duplicate_check_uses_config_entries(
    hass: HomeAssistant,
) -> None:
    """Skip the activity-sensor menu when a config entry already provides it."""
    MockConfigEntry(
        domain=DOMAIN,
        title="Activity Sensor",
        data={CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR},
        entry_id="activity",
    ).add_to_hass(hass)
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == "form"
    assert result["step_id"] == "scene"


async def test_options_scene_form_fields_have_labels(hass: HomeAssistant) -> None:
    """Give every options field a translated label instead of a raw key."""
    flow, _ = _options_flow(hass)
    translations = json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    labels = translations["options"]["step"]["scene"]["data"]

    result = await flow.async_step_init()

    data_schema = result["data_schema"]
    assert data_schema is not None
    fields = {str(marker) for marker in data_schema.schema}
    assert fields <= set(labels)
