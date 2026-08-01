"""Config flow for the Animated Scenes integration.

This module implements the config and options flows used by Home
Assistant to configure Animated Scenes. It includes small helper
functions used to parse and validate user input from the UI.
"""

import copy
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_BRIGHTNESS, CONF_ICON, CONF_LIGHTS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv
from homeassistant.util import uuid
import voluptuous as vol

from .animations import Animations
from .const import (
    ABORT_ACTIVITY_SENSOR_EXISTS,
    ABORT_ACTIVITY_SENSOR_NO_OPTIONS,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
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
    CONF_PLATFORM,
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
    ERROR_COLORS_IS_BLANK,
    ERROR_COLORS_MALFORMED,
    ERROR_SCENE_NAME_EXISTS,
)
from .scene_config import (
    SCENE_DEFAULTS,
    build_colors_from_rgb_dict,
    clean_color_rgb_dict,
    is_int_or_list,
    list_or_int_to_str,
    normalize_scene_input,
    validate_start_service_data,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)
COLOR_SELECTOR_OPTION_LIST = [
    selector.SelectOptionDict(label="Use RGB Selectors", value=COLOR_SELECTOR_RGB_UI),
    selector.SelectOptionDict(label="Configure via YAML", value=COLOR_SELECTOR_YAML),
]
RGB_UI_COLOR_DEFAULTS = {
    CONF_BRIGHTNESS: DEFAULT_BRIGHTNESS,
    CONF_COLOR_NEARBY_COLORS: DEFAULT_COLOR_NEARBY_COLORS,
    CONF_COLOR_ONE_CHANGE_PER_TICK: DEFAULT_COLOR_ONE_CHANGE_PER_TICK,
    CONF_COLOR_WEIGHT: DEFAULT_COLOR_WEIGHT,
    CONF_COLOR_ADD_COLOR: DEFAULT_COLOR_ADD_COLOR,
    CONF_COLOR_DELETE_COLOR: DEFAULT_COLOR_DELETE_COLOR,
}


def _scene_name_exists(hass: HomeAssistant, name: str, exclude_entry_id: str | None = None) -> bool:
    """Return whether another scene config entry already uses a name.

    Args:
        hass: Home Assistant instance containing config entries.
        name: Proposed runtime scene name.
        exclude_entry_id: Entry id to ignore while validating an options rename.

    Returns:
        True when another Animated Scenes scene entry uses the proposed name.

    """
    return any(
        entry.entry_id != exclude_entry_id
        and entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_SCENE
        and entry.data.get(CONF_NAME) == name
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


def _validate_yaml_runtime_data(data: dict[str, Any]) -> None:
    """Validate YAML color data using runtime fields only.

    Args:
        data: Scene configuration that may include config-flow-only fields.

    Raises:
        vol.Invalid: If the runtime service schema rejects the color data.

    """
    runtime_data = dict(data)
    runtime_data.pop(CONF_COLOR_RGB_DICT, None)
    runtime_data.pop(CONF_COLOR_SELECTOR_MODE, None)
    runtime_data.pop(CONF_ENTITY_TYPE, None)
    runtime_data.pop(CONF_ICON, None)
    runtime_data.pop(CONF_PLATFORM, None)
    validate_start_service_data(runtime_data)


def _validate_color_yaml_data(data: dict[str, Any]) -> str | None:
    """Return a color YAML validation error key, or None when valid.

    Args:
        data: Scene configuration containing YAML color data.

    Returns:
        Translation key for the validation error, or None when valid.

    """
    if data.get(CONF_COLORS) in (None, {}, []):
        return ERROR_COLORS_IS_BLANK
    if not isinstance(data.get(CONF_COLORS), list):
        return ERROR_COLORS_MALFORMED
    try:
        _validate_yaml_runtime_data(data)
    except vol.Invalid as err:
        _LOGGER.debug("Invalid YAML color payload: %s", err)
        return ERROR_COLORS_MALFORMED
    return None


def _validate_rgb_ui_runtime_data(data: dict[str, Any]) -> str | None:
    """Validate a completed RGB UI color dictionary through the runtime schema.

    Args:
        data: Completed scene configuration containing cleaned RGB UI colors.

    Returns:
        The malformed-colors error key when runtime validation fails, otherwise None.

    """
    runtime_data = dict(data)
    runtime_data[CONF_COLORS] = build_colors_from_rgb_dict(
        runtime_data.get(CONF_COLOR_RGB_DICT, {})
    )
    try:
        _validate_yaml_runtime_data(normalize_scene_input(runtime_data))
    except vol.Invalid as err:
        _LOGGER.debug("Invalid RGB UI color payload: %s", err)
        return ERROR_COLORS_MALFORMED
    return None


def _schema_default(
    user_input: dict[str, Any],
    default_dict: dict[str, Any],
    key: str,
    fallback_default: Any = None,
) -> Any:
    """Return a schema default from user input, stored defaults, or fallback."""
    return user_input.get(key, default_dict.get(key, fallback_default))


def _normalize_rgb_ui_color_input(color_data: dict[str, Any]) -> str | None:
    """Normalize submitted RGB UI color data.

    Args:
        color_data: Submitted color configuration data to validate and update.

    Returns:
        The translation key for the validation error, or ``None`` when valid.

    """
    if color_data.get(CONF_COLOR) is None:
        return ERROR_COLORS_IS_BLANK
    _LOGGER.debug(
        "Checking Brightness: %s, type: %s",
        color_data.get(CONF_BRIGHTNESS),
        type(color_data.get(CONF_BRIGHTNESS)),
    )
    brightness_check, brightness_value = is_int_or_list(
        color_data.get(CONF_BRIGHTNESS),
        BRIGHTNESS_MIN,
        BRIGHTNESS_MAX,
    )
    if not brightness_check:
        return ERROR_BRIGHTNESS_NOT_INT_OR_RANGE
    if brightness_value is None:
        brightness_value = DEFAULT_BRIGHTNESS
    color_data[CONF_BRIGHTNESS] = brightness_value
    color_data[CONF_COLOR_WEIGHT] = round(color_data.get(CONF_COLOR_WEIGHT, DEFAULT_COLOR_WEIGHT))
    color_data[CONF_COLOR_NEARBY_COLORS] = round(
        color_data.get(CONF_COLOR_NEARBY_COLORS, DEFAULT_COLOR_NEARBY_COLORS)
    )
    for key, value in RGB_UI_COLOR_DEFAULTS.items():
        color_data.setdefault(key, value)
    return None


def _build_schema(
    user_input: dict[str, Any] | None,
    default_dict: dict[str, Any],
    options_flow: bool = False,
) -> vol.Schema:
    """Build a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}
    default = partial(_schema_default, user_input, default_dict)

    build_schema = vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default=default(CONF_NAME),
            ): selector.TextSelector(selector.TextSelectorConfig()),
        }
    )
    if not options_flow:
        build_schema = build_schema.extend(
            {
                vol.Optional(
                    CONF_ICON,
                    default=default(CONF_ICON, DEFAULT_ICON),
                ): selector.IconSelector(selector.IconSelectorConfig()),
            }
        )
    build_schema = build_schema.extend(
        {
            vol.Optional(
                CONF_PRIORITY,
                default=default(CONF_PRIORITY, DEFAULT_PRIORITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-100,
                    max=100,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_CHANGE_FREQUENCY,
                default=list_or_int_to_str(
                    default(CONF_CHANGE_FREQUENCY, DEFAULT_CHANGE_FREQUENCY)
                ),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_TRANSITION,
                default=list_or_int_to_str(default(CONF_TRANSITION, DEFAULT_TRANSITION)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_CHANGE_AMOUNT,
                default=list_or_int_to_str(default(CONF_CHANGE_AMOUNT, DEFAULT_CHANGE_AMOUNT)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_BRIGHTNESS,
                default=list_or_int_to_str(default(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_CHANGE_SEQUENCE,
                default=default(CONF_CHANGE_SEQUENCE, DEFAULT_CHANGE_SEQUENCE),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_ANIMATE_BRIGHTNESS,
                default=default(CONF_ANIMATE_BRIGHTNESS, DEFAULT_ANIMATE_BRIGHTNESS),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_ANIMATE_COLOR,
                default=default(CONF_ANIMATE_COLOR, DEFAULT_ANIMATE_COLOR),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_IGNORE_OFF,
                default=default(CONF_IGNORE_OFF, DEFAULT_IGNORE_OFF),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_RESTORE,
                default=default(CONF_RESTORE, DEFAULT_RESTORE),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_RESTORE_POWER,
                default=default(CONF_RESTORE_POWER, DEFAULT_RESTORE_POWER),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Required(CONF_LIGHTS, default=default(CONF_LIGHTS, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=[Platform.LIGHT], multiple=True),
            ),
        }
    )

    return build_schema.extend(
        {
            vol.Required(
                CONF_COLOR_SELECTOR_MODE,
                default=default(CONF_COLOR_SELECTOR_MODE, ""),
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


def _build_color_yaml_schema(
    user_input: dict[str, Any] | None, default_dict: dict[str, Any]
) -> vol.Schema:
    """Build a color YAML schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}
    default = partial(_schema_default, user_input, default_dict)

    build_schema = vol.Schema({})

    colors_default = default(CONF_COLORS)
    if colors_default is None or colors_default == {}:
        build_schema = build_schema.extend(
            {
                vol.Required(CONF_COLORS): selector.ObjectSelector(),
            }
        )
    else:
        build_schema = build_schema.extend(
            {
                vol.Required(CONF_COLORS, default=colors_default): selector.ObjectSelector(),
            }
        )

    return build_schema


def _build_color_rgb_ui_schema(
    user_input: dict[str, Any] | None,
    default_dict: dict[str, Any],
    options_flow: bool = False,
    is_last_color: bool = False,
) -> vol.Schema:
    """Build a color RGB UI schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}
    default = partial(_schema_default, user_input, default_dict)

    color_default = default(CONF_COLOR)
    color_key = (
        vol.Required(CONF_COLOR, default=color_default)
        if color_default is not None
        else vol.Required(CONF_COLOR)
    )
    build_schema = vol.Schema(
        {
            color_key: selector.ColorRGBSelector(selector.ColorRGBSelectorConfig()),
            vol.Optional(
                CONF_BRIGHTNESS,
                default=list_or_int_to_str(default(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Optional(
                CONF_COLOR_WEIGHT,
                default=default(CONF_COLOR_WEIGHT, DEFAULT_COLOR_WEIGHT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=255,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_COLOR_ONE_CHANGE_PER_TICK,
                default=default(CONF_COLOR_ONE_CHANGE_PER_TICK, DEFAULT_COLOR_ONE_CHANGE_PER_TICK),
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(
                CONF_COLOR_NEARBY_COLORS,
                default=default(CONF_COLOR_NEARBY_COLORS, DEFAULT_COLOR_NEARBY_COLORS),
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
                    default=default(CONF_COLOR_ADD_COLOR, DEFAULT_COLOR_ADD_COLOR),
                ): cv.boolean,
            }
        )

    if options_flow:
        build_schema = build_schema.extend(
            {
                vol.Required(
                    CONF_COLOR_DELETE_COLOR,
                    default=default(CONF_COLOR_DELETE_COLOR, DEFAULT_COLOR_DELETE_COLOR),
                ): cv.boolean,
            }
        )

    return build_schema


class AnimatedScenesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Animated Scenes.

    This class implements the steps shown to the user when creating an
    instance of the integration via the UI or importing YAML.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._data[CONF_COLOR_RGB_DICT] = {}
        self._data[CONF_COLORS] = {}
        self._entry = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step.

        Presents a menu to choose between creating an activity sensor or
        a scene entry, depending on whether an activity sensor already
        exists.
        """
        activity_sensor_exists = any(
            entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_ACTIVITY_SENSOR
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )
        if activity_sensor_exists:
            return await self.async_step_scene(user_input=user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=["activity_sensor", "scene"],
        )

    async def async_step_activity_sensor(self, _: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create an activity sensor config entry immediately."""
        if any(
            entry.data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_ACTIVITY_SENSOR
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ):
            return self.async_abort(reason=ABORT_ACTIVITY_SENSOR_EXISTS)
        self._data.update({CONF_NAME: "Activity Sensor", CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR})
        return self.async_create_entry(title="Activity Sensor", data=self._data)

    async def async_step_scene(
        self, user_input: dict[str, Any] | None = None, yaml_import: bool = False
    ) -> ConfigFlowResult:
        """Handle the scene creation step.

        Validates and normalizes user input before continuing to color
        configuration steps or creating the config entry.
        """
        errors: dict[str, Any] = {}

        # Defaults
        defaults = {CONF_ICON: DEFAULT_ICON, **SCENE_DEFAULTS}

        if user_input is not None:
            self._data.update(user_input)
            self._data.update({CONF_ENTITY_TYPE: ENTITY_SCENE})
            if _scene_name_exists(self.hass, self._data[CONF_NAME]):
                errors["base"] = ERROR_SCENE_NAME_EXISTS
            else:
                try:
                    self._data = normalize_scene_input(self._data)
                except vol.Invalid as err:
                    errors["base"] = str(err)
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            if not errors:
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
            data_schema=_build_schema(user_input, defaults),
            errors=errors,
        )

    async def async_step_color_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration when the user chooses YAML input.

        Args:
            user_input: Submitted YAML color configuration, if any.

        Returns:
            The next config-flow result for validation, form display, or entry creation.

        """
        errors: dict[str, Any] = {}

        if user_input is not None:
            self._data.update(user_input)
            if error := _validate_color_yaml_data(self._data):
                errors["base"] = error
            if not errors and _scene_name_exists(self.hass, self._data[CONF_NAME]):
                errors["base"] = ERROR_SCENE_NAME_EXISTS
            if not errors:
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(
            step_id="color_yaml",
            data_schema=_build_color_yaml_schema(user_input, {}),
            errors=errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
            },
        )

    async def async_step_color_rgb_ui(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration when the user uses the RGB UI selectors."""
        errors: dict[str, Any] = {}

        if user_input is not None:
            if error := _normalize_rgb_ui_color_input(user_input):
                errors["base"] = error
            if not errors:
                color_uuid = uuid.random_uuid_hex()
                self._data.setdefault(CONF_COLOR_RGB_DICT, {}).update({color_uuid: user_input})
                if user_input.get(CONF_COLOR_ADD_COLOR, False):
                    return await self.async_step_color_rgb_ui()
                self._data.update(
                    {
                        CONF_COLOR_RGB_DICT: clean_color_rgb_dict(
                            self._data.get(CONF_COLOR_RGB_DICT, {})
                        )
                    }
                )
                if error := _validate_rgb_ui_runtime_data(self._data):
                    errors["base"] = error
                elif _scene_name_exists(self.hass, self._data[CONF_NAME]):
                    errors["base"] = ERROR_SCENE_NAME_EXISTS
                else:
                    return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        return self.async_show_form(
            step_id="color_rgb_ui",
            data_schema=_build_color_rgb_ui_schema(user_input, RGB_UI_COLOR_DEFAULTS),
            errors=errors,
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
    """Handle scene options while storing updates back into config entry data."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self.config = config_entry
        self._data = dict(config_entry.data)
        rgb_dict = self._data.get(CONF_COLOR_RGB_DICT, {})
        self._data[CONF_COLOR_RGB_DICT] = copy.deepcopy(rgb_dict)
        self._rgb_ui_color_keys = list(rgb_dict)
        self._rgb_ui_color_values = list(rgb_dict.values())
        self._rgb_ui_color_max = len(self._rgb_ui_color_keys)
        self._rgb_ui_color_index = 0

    async def _async_stop_previous_animation_if_renamed(self) -> None:
        """Stop an active scene using its stored name before saving a rename."""
        previous_name = self.config.data.get(CONF_NAME)
        new_name = self._data.get(CONF_NAME)
        manager = Animations.instance
        if (
            manager
            and previous_name
            and previous_name != new_name
            and previous_name in manager.animations
        ):
            await manager.stop_by_name(previous_name)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if self._data.get(CONF_ENTITY_TYPE, ENTITY_SCENE) == ENTITY_ACTIVITY_SENSOR:
            return self.async_abort(reason=ABORT_ACTIVITY_SENSOR_NO_OPTIONS)
        return await self.async_step_scene(user_input=user_input)

    async def async_step_scene(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the scene options step in the options flow.

        Validate and normalize the provided options and either proceed to
        color configuration steps or update the entry data.
        """
        errors: dict[str, Any] = {}

        # Defaults
        defaults = {CONF_ICON: DEFAULT_ICON, **SCENE_DEFAULTS}

        if user_input is not None:
            self._data.update(user_input)
            self._data.update({CONF_ENTITY_TYPE: ENTITY_SCENE})
            if _scene_name_exists(self.hass, self._data[CONF_NAME], self.config.entry_id):
                errors["base"] = ERROR_SCENE_NAME_EXISTS
            else:
                try:
                    self._data = normalize_scene_input(self._data)
                except vol.Invalid as err:
                    errors["base"] = str(err)
            for k, v in defaults.items():
                self._data.setdefault(k, v)
            if not errors:
                if (
                    self._data.get(CONF_COLOR_SELECTOR_MODE, COLOR_SELECTOR_RGB_UI)
                    == COLOR_SELECTOR_RGB_UI
                ):
                    return await self.async_step_color_rgb_ui()
                return await self.async_step_color_yaml()

        return self.async_show_form(
            step_id="scene",
            data_schema=_build_schema(user_input, self._data, options_flow=True),
            errors=errors,
            description_placeholders={"scene_name": self._data[CONF_NAME]},
        )

    async def async_step_color_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration in YAML mode within the options flow.

        Args:
            user_input: Submitted YAML color configuration, if any.

        Returns:
            The next options-flow result for validation, form display, or entry update.

        """
        errors: dict[str, Any] = {}

        if user_input is not None:
            self._data.update(user_input)
            if error := _validate_color_yaml_data(self._data):
                errors["base"] = error
            if not errors and _scene_name_exists(
                self.hass, self._data[CONF_NAME], self.config.entry_id
            ):
                errors["base"] = ERROR_SCENE_NAME_EXISTS
            if not errors:
                self._data.update({CONF_COLOR_RGB_DICT: {}})
                await self._async_stop_previous_animation_if_renamed()
                self.hass.config_entries.async_update_entry(
                    self.config,
                    data=self._data,
                    options=self.config.options,
                    title=self._data[CONF_NAME],
                )
                await self.hass.config_entries.async_reload(self.config.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="color_yaml",
            data_schema=_build_color_yaml_schema(user_input, self._data),
            errors=errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
            },
        )

    async def async_step_color_rgb_ui(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle color configuration using the RGB UI selectors in options."""
        errors: dict[str, Any] = {}

        if self._rgb_ui_color_index + 1 <= self._rgb_ui_color_max:
            color_data = copy.deepcopy(self._rgb_ui_color_values[self._rgb_ui_color_index])
        else:
            color_data = {}

        if user_input is not None:
            color_data.update(user_input)
            if error := _normalize_rgb_ui_color_input(color_data):
                errors["base"] = error
            if not errors:
                if self._rgb_ui_color_index + 1 <= self._rgb_ui_color_max:
                    self._data.setdefault(CONF_COLOR_RGB_DICT, {}).update(
                        {self._rgb_ui_color_keys[self._rgb_ui_color_index]: color_data}
                    )
                else:
                    color_uuid = uuid.random_uuid_hex()
                    self._data.setdefault(CONF_COLOR_RGB_DICT, {}).update({color_uuid: color_data})
                if self._rgb_ui_color_index + 1 < self._rgb_ui_color_max or (
                    self._rgb_ui_color_index + 1 >= self._rgb_ui_color_max
                    and color_data.get(CONF_COLOR_ADD_COLOR, False)
                ):
                    self._rgb_ui_color_index += 1
                    return await self.async_step_color_rgb_ui()
                self._data.update({CONF_COLORS: {}})
                cleaned_color_rgb_dict = clean_color_rgb_dict(
                    self._data.get(CONF_COLOR_RGB_DICT, {})
                )
                if not cleaned_color_rgb_dict:
                    errors["base"] = ERROR_COLORS_IS_BLANK
                else:
                    self._data.update({CONF_COLOR_RGB_DICT: cleaned_color_rgb_dict})
                    if error := _validate_rgb_ui_runtime_data(self._data):
                        errors["base"] = error
                    elif _scene_name_exists(self.hass, self._data[CONF_NAME], self.config.entry_id):
                        errors["base"] = ERROR_SCENE_NAME_EXISTS
                if errors:
                    return self.async_show_form(
                        step_id="color_rgb_ui",
                        data_schema=_build_color_rgb_ui_schema(
                            user_input,
                            color_data,
                            options_flow=True,
                            is_last_color=True,
                        ),
                        errors=errors,
                        description_placeholders={"scene_name": self._data[CONF_NAME]},
                    )
                await self._async_stop_previous_animation_if_renamed()
                self.hass.config_entries.async_update_entry(
                    self.config,
                    data=self._data,
                    options=self.config.options,
                    title=self._data[CONF_NAME],
                )
                await self.hass.config_entries.async_reload(self.config.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="color_rgb_ui",
            data_schema=_build_color_rgb_ui_schema(
                user_input,
                color_data,
                options_flow=True,
                is_last_color=(self._rgb_ui_color_index + 1 >= self._rgb_ui_color_max),
            ),
            errors=errors,
            description_placeholders={
                "component_color_config_url": COMPONENT_COLOR_CONFIG_URL,
                "color_count": str(self._rgb_ui_color_index + 1),
                "color_max": str(self._rgb_ui_color_max),
            },
        )
