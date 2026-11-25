"""Shared entity helpers for the Animated Scenes integration."""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, INTEGRATION_NAME


def integration_device_info() -> DeviceInfo:
    """Return the device that groups every Animated Scenes entity.

    Scene switches and the activity sensor must report identical device
    metadata so Home Assistant registers them under one device.

    Returns:
        A new device registry payload for the integration device.

    """
    return {
        "identifiers": {(DOMAIN, "animated_scenes")},
        "name": INTEGRATION_NAME,
        "manufacturer": INTEGRATION_NAME,
    }
