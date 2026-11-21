"""Shared helpers that exercise Animated Scenes through Home Assistant services."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.light import LIGHT_TURN_ON_SCHEMA
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv


def register_light_services(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Register light services that enforce Home Assistant's real turn-on schema.

    Args:
        hass: Home Assistant test instance.

    Returns:
        A list that records each accepted ``light.turn_on`` payload.

    """
    calls: list[dict[str, Any]] = []

    async def _turn_on(call: ServiceCall) -> None:
        """Record a valid turn-on call and mark its lights as on."""
        calls.append(dict(call.data))
        for entity_id in call.data["entity_id"]:
            state = hass.states.get(entity_id)
            hass.states.async_set(entity_id, "on", dict(state.attributes) if state else {})

    async def _turn_off(_: ServiceCall) -> None:
        """Accept a turn-off call."""

    hass.services.async_register(
        "light",
        "turn_on",
        _turn_on,
        schema=cv.make_entity_service_schema(LIGHT_TURN_ON_SCHEMA),  # type: ignore[arg-type, unused-ignore]
    )
    hass.services.async_register(
        "light",
        "turn_off",
        _turn_off,
        schema=cv.make_entity_service_schema({}),  # type: ignore[arg-type, unused-ignore]
    )
    return calls


def animation_tasks(name: str) -> list[asyncio.Task[Any]]:
    """Return unfinished animation loop tasks for a scene name."""
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == f"animated_scenes_{name}" and not task.done()
    ]
