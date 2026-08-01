"""Tests for Animated Scenes activity sensor."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.animated_scenes.animations import Animations
from custom_components.animated_scenes.config_flow import AnimatedScenesConfigFlow
from custom_components.animated_scenes.const import (
    CONF_ENTITY_TYPE,
    DOMAIN,
    ENTITY_ACTIVITY_SENSOR,
    EVENT_NAME_CHANGE,
    EVENT_STATE_STARTED,
    INTEGRATION_NAME,
)
from custom_components.animated_scenes.sensor import AnimatedScenesSensor


def test_sensor_exposes_animated_scenes_device_info(hass: HomeAssistant) -> None:
    """Group activity sensor entities under the Animated Scenes device."""
    sensor = AnimatedScenesSensor(hass)

    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "animated_scenes")},
        "name": INTEGRATION_NAME,
        "manufacturer": INTEGRATION_NAME,
    }


@pytest.mark.asyncio
async def test_activity_sensor_writes_state_on_animation_event(hass: HomeAssistant) -> None:
    """Write sensor state immediately when animation lifecycle events fire.

    The activity sensor reports manager state, so it should react to the
    manager's event bus notifications instead of waiting for polling.
    """
    manager = Animations(hass)
    Animations.instance = manager
    sensor = AnimatedScenesSensor(hass)
    sensor.hass = hass

    assert sensor.should_poll is False

    with patch.object(AnimatedScenesSensor, "async_write_ha_state") as write_state:
        await sensor.async_added_to_hass()

        hass.bus.async_fire(
            EVENT_NAME_CHANGE, {"animation": "Spooky", "state": EVENT_STATE_STARTED}
        )
        await hass.async_block_till_done()

    write_state.assert_called_once()


@pytest.mark.asyncio
async def test_activity_sensor_duplicate_check_uses_config_entries(
    hass: HomeAssistant,
) -> None:
    """Detect an existing activity sensor from loaded config entries.

    Config flows can run before entries have runtime data, so duplicate
    activity-sensor suppression must inspect Home Assistant config entries.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Activity Sensor",
        data={CONF_ENTITY_TYPE: ENTITY_ACTIVITY_SENSOR},
        source="user",
        entry_id="activity",
    )
    entry.add_to_hass(hass)
    flow = AnimatedScenesConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == "form"
    assert result["step_id"] == "scene"
