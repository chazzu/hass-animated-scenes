"""The Animated Scenes integration."""
import asyncio

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN, ATTR_RGB_COLOR, ATTR_XY_COLOR, ATTR_COLOR_TEMP, ATTR_HS_COLOR,
    ATTR_KELVIN)
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_TURN_ON, SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.event import async_track_state_change_event
from .const import DOMAIN, CONF_EXTERNAL_SWITCHES

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({
    vol.Optional(CONF_EXTERNAL_SWITCHES): cv.entity_ids,
})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["switch"]


async def async_setup(hass: HomeAssistant, config: dict):
    try:
        switches = config.get(DOMAIN).get(CONF_EXTERNAL_SWITCHES)    
        if switches:
            GLOBAL_SCENES.add_switches(switches)
    except Exception:
        print("Oh well")
    await GLOBAL_SCENES.set_hass(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class AnimatedScenes:
    def __init__(self):
        self.hass: HomeAssistant = None
        self.switches = []
        self.scenes = {}
        self.active_scene = None
        self.stored_state = {}

    async def activate_scene(self, scene):
        if not self.hass:
            return

        active_scene = None
        if self.active_scene and self.active_scene in self.scenes:
            active_scene = self.scenes[self.active_scene]

        if active_scene and active_scene.restore:
            restore_lights = (list(list(set(active_scene.lights) - set(scene.lights))
                                   + list(set(scene.lights) - set(active_scene.lights))))
            await self.restore_state(restore_lights)

        await self.turn_off_all(scene.entity_id)

        self.store_state(scene.lights)
        self.active_scene = scene.entity_id
        await scene.initialize()

    def add_scene(self, scene):
        self.scenes[scene.entity_id] = scene

    def add_switches(self, switches):
        self.switches.extend(switches)

    async def deactivate_scene(self, scene):
        if not self.hass:
            return

        if scene.restore and self.active_scene == scene.entity_id:
            await self.restore_state(scene.lights)

        if self.active_scene == scene.entity_id:
            self.active_scene = None

    async def set_hass(self, hass: HomeAssistant):
        self.hass = hass
        async_track_state_change_event(hass, self.switches, self.external_switch_changed)

    def store_state(self, lights):
        if not self.hass:
            return

        for light in lights:
            if light not in self.stored_state and self.hass.states.get(light).state != 'off':
                self.stored_state[light]: State = self.hass.states.get(light)

    async def restore_state(self, lights):
        if not self.hass:
            return

        for light in lights:
            if light in self.stored_state:
                state: State = self.stored_state[light]
                if state.state == 'on':
                    await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_ON,
                                                        self._build_attributes_from_state(state))
                else:
                    await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {'entity_id': light})
                del self.stored_state[light]

    async def turn_off_all(self, on_switch=None):
        for switch in self.switches:
            if on_switch != switch:
                await self.hass.services.async_call(SWITCH_DOMAIN, SERVICE_TURN_OFF, {'entity_id': switch})
        for switch in self.scenes:
            if on_switch != switch:
                await self.hass.services.async_call(SWITCH_DOMAIN, SERVICE_TURN_OFF, {'entity_id': switch})

    async def external_switch_changed(self, event):
        state = event.data.get('new_state')
        entity_id = event.data.get('entity_id')
        if state.state == 'on':
            await self.turn_off_all(entity_id)
            self.active_scene = entity_id
        elif state.state == 'off' and self.active_scene == entity_id:
            await self.turn_off_all()
            self.active_scene = None

    def _build_attributes_from_state(self, state):
        attributes = {
            'entity_id': state.entity_id,
            'brightness': state.attributes.get('brightness'),
            'transition': 1
        }
        exclusive_properties = [ATTR_RGB_COLOR, ATTR_XY_COLOR, ATTR_HS_COLOR, ATTR_COLOR_TEMP, ATTR_KELVIN]
        for attr in exclusive_properties:
            value = state.attributes.get(attr)
            if value:
                attributes[attr] = value
                break

        return attributes


GLOBAL_SCENES = AnimatedScenes()
