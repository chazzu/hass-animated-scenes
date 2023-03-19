from homeassistant import config_entries
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import (
	DOMAIN,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	VERSION = 1

	async def async_step_user(self, user_data=None):
		return self.async_create_entry(title="Animated Scenes", data={})

	async def async_step_import(self, user_data=None):
		return self.async_create_entry(title="Animated Scenes", data={})
