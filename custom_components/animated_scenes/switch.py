import copy
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_BRIGHTNESS,
    CONF_ICON,
    CONF_LIGHTS,
    CONF_NAME,
    MATCH_ALL,
)
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import slugify

from .animations import START_SERVICE_CONFIG, Animations
from .const import (
    COLOR_SELECTOR_RGB_UI,
    CONF_ANIMATE_BRIGHTNESS,
    CONF_ANIMATE_COLOR,
    CONF_CHANGE_AMOUNT,
    CONF_CHANGE_FREQUENCY,
    CONF_CHANGE_SEQUENCE,
    CONF_COLOR_RGB,
    CONF_COLOR_RGB_DICT,
    CONF_COLOR_SELECTOR_MODE,
    CONF_COLOR_TYPE,
    CONF_COLORS,
    CONF_ENTITY_TYPE,
    CONF_IGNORE_OFF,
    CONF_PLATFORM,
    CONF_PRIORITY,
    CONF_RESTORE,
    CONF_RESTORE_POWER,
    CONF_TRANSITION,
    DOMAIN,
    INTEGRATION_NAME,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA_PART = vol.Schema(
    {
        vol.Required(CONF_PLATFORM): DOMAIN,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA_PART.extend(START_SERVICE_CONFIG)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:

    _LOGGER.debug(
        f"[async_setup_platform] config name: {config.get(CONF_NAME, None)}, "
        f"existing scenes title list: {[x.title for x in hass.config_entries.async_entries(DOMAIN)]}"
    )
    async_create_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        f"deprecated_yaml_{DOMAIN}",
        breaks_in_ha_version="2025.1",
        is_fixable=False,
        is_persistent=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        translation_placeholders={
            "domain": DOMAIN,
            "integration_title": INTEGRATION_NAME,
        },
    )
    if config.get(CONF_NAME, None) not in [
        x.title for x in hass.config_entries.async_entries(DOMAIN)
    ]:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=config,
            )
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup the Animated Scene Switch with a config_entry (config_flow)."""

    config = hass.data.get(DOMAIN).get(config_entry.entry_id)
    unique_id = config_entry.entry_id
    async_add_entities([AnimatedSceneSwitch(hass, config, unique_id)])
    return True


class AnimatedSceneSwitch(SwitchEntity):
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, hass, config, unique_id):
        _LOGGER.debug(f"[AnimatedSceneSwitch init] config: {config}")
        _LOGGER.debug(f"[AnimatedSceneSwitch init] unique_id: {unique_id}")
        self.hass = hass
        self._config = config
        self._attr_name: str = config.get(CONF_NAME)
        self._attr_icon = config.get(CONF_ICON)
        self._attr_is_on: bool = False
        self.entity_id = ENTITY_ID_FORMAT.format(slugify(f"{DOMAIN}_{self._attr_name}"))
        self._attr_unique_id = unique_id
        self._animation_config = {}
        hass.async_create_task(self._async_setup_animation_fields())

    async def _async_setup_animation_fields(self):
        if self._config.get(CONF_COLOR_SELECTOR_MODE, None) == COLOR_SELECTOR_RGB_UI:
            await self._async_build_colors_from_rgb_dict()
        self._animation_config = copy.deepcopy(self._config)
        self._animation_config.pop(CONF_PLATFORM, None)
        self._animation_config.pop(CONF_ICON, None)
        self._animation_config.pop(CONF_ENTITY_TYPE, None)
        self._animation_config.pop(CONF_COLOR_RGB_DICT, None)
        self._animation_config.pop(CONF_COLOR_SELECTOR_MODE, None)
        _LOGGER.debug(f"[async_setup_animation_fields] config: {self._config}")
        _LOGGER.debug(
            f"[async_setup_animation_fields] animation_config: {self._animation_config}"
        )

    async def _async_build_colors_from_rgb_dict(self):
        color_list = list(copy.deepcopy(self._config.get(CONF_COLOR_RGB_DICT)).values())
        for color in color_list:
            color.update({CONF_COLOR_TYPE: CONF_COLOR_RGB})
        _LOGGER.debug(f"[async_build_colors_from_rgb_dict] color_list: {color_list}")
        self._config.update({CONF_COLORS: color_list})

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the state attributes."""
        return {
            CONF_PRIORITY: self._config.get(CONF_PRIORITY),
            CONF_CHANGE_FREQUENCY: self._config.get(CONF_CHANGE_FREQUENCY),
            CONF_TRANSITION: self._config.get(CONF_TRANSITION),
            CONF_CHANGE_AMOUNT: self._config.get(CONF_CHANGE_AMOUNT),
            CONF_BRIGHTNESS: self._config.get(CONF_BRIGHTNESS),
            CONF_CHANGE_SEQUENCE: self._config.get(CONF_CHANGE_SEQUENCE),
            CONF_ANIMATE_BRIGHTNESS: self._config.get(CONF_ANIMATE_BRIGHTNESS),
            CONF_ANIMATE_COLOR: self._config.get(CONF_ANIMATE_COLOR),
            CONF_IGNORE_OFF: self._config.get(CONF_IGNORE_OFF),
            CONF_RESTORE: self._config.get(CONF_RESTORE),
            CONF_RESTORE_POWER: self._config.get(CONF_RESTORE_POWER),
            CONF_LIGHTS: self._config.get(CONF_LIGHTS),
            CONF_COLORS: self._config.get(CONF_COLORS),
        }

    async def async_turn_on(self, **kwargs: vol.Any) -> None:
        if not self._attr_is_on:
            self._attr_is_on = True
            await Animations.instance.start(self._animation_config)

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        await Animations.instance.stop({"name": self._attr_name})
