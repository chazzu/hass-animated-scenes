"""Diagnostics support for Animated Scenes.

This module owns Home Assistant diagnostics output for config entries. It
reports safe config-entry metadata and runtime counters while redacting entity
identifiers that could expose user-specific rooms, devices, or naming schemes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .animations import Animations

TO_REDACT: set[str] = {"animated_scene_switch", "entity_id", "lights", "name"}


def _redact(value: Any) -> Any:
    """Redact entity identifiers from diagnostics payloads.

    Args:
        value: Arbitrary diagnostics value from config-entry data or options.

    Returns:
        A recursively redacted copy for mappings and lists, or the original
        scalar value when no redaction is needed.

    """
    if isinstance(value, dict):
        return {
            key: ("**REDACTED**" if key in TO_REDACT else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an Animated Scenes config entry.

    Args:
        hass: Home Assistant instance requesting diagnostics.
        entry: Config entry whose data should be summarized.

    Returns:
        A diagnostics payload with redacted entry data/options and runtime
        counts from the active animation manager.

    """
    runtime = _runtime_diagnostics()
    return {
        "entry": {
            "title": "**REDACTED**",
            "data": _redact(dict(entry.data)),
            "options": _redact(dict(entry.options)),
        },
        "runtime": runtime,
    }


def _runtime_diagnostics() -> dict[str, int]:
    """Return runtime animation counters, or zeros before manager initialization."""
    manager = Animations.instance
    if manager is None:
        return {
            "active_animation_count": 0,
            "active_light_count": 0,
            "stored_state_count": 0,
        }
    return {
        "active_animation_count": len(manager.animations),
        "active_light_count": len(manager.light_owner),
        "stored_state_count": len(manager.states),
    }
