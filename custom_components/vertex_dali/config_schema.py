"""YAML schema for vertex_dali.

Unlike modbus_meter_eastron, there's no shared per-model "profile" here --
every device's register is a unique DALI short_address/port pair on the same
controller, so the compact form is inline: controller -> room -> group ->
[devices]. Read addresses are derived from short_address/dali_port via the
vendor formula (const.py); write registers have no vendor formula (installer-
assigned, see memory.ai/vertex-individual-control.md) so they're listed
explicitly per group and per device.
"""
from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_CONTROLLERS,
    CONF_DALI_PORT,
    CONF_DEVICES,
    CONF_GROUPS,
    CONF_ROOMS,
    CONF_SHORT_ADDRESS,
    CONF_WRITE_REGISTER,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required(CONF_SHORT_ADDRESS): cv.positive_int,
        vol.Optional(CONF_DALI_PORT, default=0): cv.positive_int,
        vol.Required(CONF_WRITE_REGISTER): cv.positive_int,
    }
)

GROUP_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required(CONF_WRITE_REGISTER): cv.positive_int,
        vol.Required(CONF_DEVICES): [DEVICE_SCHEMA],
    }
)

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required(CONF_GROUPS): [GROUP_SCHEMA],
    }
)

CONTROLLER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("host"): cv.string,
        vol.Optional("port", default=DEFAULT_PORT): cv.port,
        vol.Optional("timeout", default=DEFAULT_TIMEOUT): vol.Coerce(float),
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): vol.Coerce(float),
        vol.Optional("retries", default=DEFAULT_RETRIES): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Required(CONF_ROOMS): [ROOM_SCHEMA],
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema({vol.Required(CONF_CONTROLLERS): [CONTROLLER_SCHEMA]}),
    },
    extra=vol.ALLOW_EXTRA,
)


def _slug(text: str) -> str:
    return text.lower().replace(".", "_").replace("/", "_").replace("\\", "_")


def flatten_devices(controller: dict) -> list[dict]:
    """One entry per individually-addressable luminaire across every room/group."""
    out = []
    for room in controller[CONF_ROOMS]:
        for group in room[CONF_GROUPS]:
            for device in group[CONF_DEVICES]:
                out.append(
                    {
                        **device,
                        "room": room["name"],
                        "group": group["name"],
                        "device_id": _slug(f"{room['name']}_{device['name']}"),
                    }
                )
    return out


def flatten_groups(controller: dict) -> list[dict]:
    out = []
    for room in controller[CONF_ROOMS]:
        for group in room[CONF_GROUPS]:
            out.append(
                {
                    "name": group["name"],
                    CONF_WRITE_REGISTER: group[CONF_WRITE_REGISTER],
                    "room": room["name"],
                    "group_id": _slug(f"{room['name']}_{group['name']}"),
                    "member_device_ids": [
                        _slug(f"{room['name']}_{d['name']}") for d in group[CONF_DEVICES]
                    ],
                }
            )
    return out
