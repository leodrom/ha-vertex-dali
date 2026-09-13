"""vertex_dali: Modbus-based control of Vertex/Glamox/ES-SYSTEM DALI-2 lighting.

Replaces the earlier YAML-only approach (modbus: sensors + input_number +
automation + template: light, one full copy of each per luminaire/group --
see memory.ai/vertex-individual-control.md) with generated entities driven
by a compact per-device/group register list. Same pattern as
modbus_meter_eastron: YAML stays as the source of truth for "what exists at
which address", but decoding/state/control logic lives in Python instead of
being duplicated per entity in YAML.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .config_schema import CONFIG_SCHEMA, flatten_devices, flatten_groups
from .const import DOMAIN
from .coordinator import VertexDaliCoordinator

_LOGGER = logging.getLogger(__name__)

__all__ = ["CONFIG_SCHEMA"]

PLATFORMS = [Platform.LIGHT]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    for controller_conf in config[DOMAIN]["controllers"]:
        hass.async_create_task(
            hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=controller_conf)
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller_conf = entry.data
    devices = flatten_devices(controller_conf)
    groups = flatten_groups(controller_conf)

    coordinator = VertexDaliCoordinator(hass, controller_conf, devices)
    hass.async_create_task(coordinator.async_refresh())

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "devices": devices,
        "groups": groups,
        "controller_name": controller_conf["name"],
    }

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, controller_conf["name"])},
        name=controller_conf["name"],
        manufacturer="Glamox / ES-SYSTEM",
        model="Vertex DALI-2 controller",
        model_id=f"{controller_conf['host']}:{controller_conf['port']}",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "vertex_dali: controller '%s' (%s:%s) set up with %d device(s), %d group(s)",
        controller_conf["name"], controller_conf["host"], controller_conf["port"],
        len(devices), len(groups),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data is not None:
            await data["coordinator"].async_shutdown()
    return unload_ok
