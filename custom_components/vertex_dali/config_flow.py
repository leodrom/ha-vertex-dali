"""Read-only import flow: turns each YAML-configured controller into a real ConfigEntry.

Same rationale as modbus_meter_eastron/config_flow.py -- configuration stays
in YAML, this only exists so Home Assistant can own Device Registry entries
for the controller -> group/luminaire hierarchy.
"""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class VertexDaliConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Import-only config flow, one entry per controller defined in YAML."""

    VERSION = 1

    async def async_step_import(self, import_data: dict) -> Any:
        await self.async_set_unique_id(import_data["name"])
        self._abort_if_unique_id_configured(updates=import_data)
        return self.async_create_entry(title=import_data["name"], data=import_data)

    async def async_step_user(self, user_input: dict | None = None) -> Any:
        return self.async_abort(reason="yaml_only")
