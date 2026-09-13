"""Light platform for vertex_dali.

Two entity kinds:
  - VertexLuminaireLight: one real DALI luminaire. State/brightness comes
    from the coordinator's polled Actual Level (ground truth); turning on
    without an explicit brightness restores the last known non-zero level.
  - VertexGroupLight: a Vertex "primary group" command channel. There is no
    per-group Input Register (confirmed -- see memory.ai), so a group's
    state is whatever HA itself last commanded, persisted via RestoreEntity
    across restarts, not read back from hardware.
"""
from __future__ import annotations

import logging

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_schema import _slug
from .const import CONF_WRITE_REGISTER, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _pct_to_brightness(pct: float) -> int:
    return round(pct * 2.55)


def _brightness_to_pct(brightness: int) -> int:
    return round(brightness / 2.55)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    controller_name = data["controller_name"]

    entities: list[LightEntity] = []
    for device in data["devices"]:
        # via_device points at the device's OWN group (not the controller
        # directly) so the group's device page lists its member luminaires,
        # same mechanism a Zigbee/Z-Wave hub uses to list connected devices.
        group_id = _slug(f"{device['room']}_{device['group']}")
        device_info = DeviceInfo(
            identifiers={(DOMAIN, device["device_id"])},
            name=f"{device['room']}/{device['name']}",
            manufacturer="Glamox / ES-SYSTEM",
            model="Vertex DALI-2 luminaire",
            via_device=(DOMAIN, group_id),
        )
        entities.append(VertexLuminaireLight(coordinator, device, device_info))

    for group in data["groups"]:
        device_info = DeviceInfo(
            identifiers={(DOMAIN, group["group_id"])},
            name=f"{group['room']}/{group['name']} (Group)",
            manufacturer="Glamox / ES-SYSTEM",
            model="Vertex DALI-2 primary group",
            via_device=(DOMAIN, controller_name),
        )
        entities.append(VertexGroupLight(coordinator, group, device_info))

    async_add_entities(entities)


class VertexLuminaireLight(CoordinatorEntity, RestoreEntity, LightEntity):
    """One physical DALI luminaire, read+written via Modbus."""

    _attr_has_entity_name = False
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator, device: dict, device_info: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._device_id = device["device_id"]
        self._write_register = device[CONF_WRITE_REGISTER]
        # "_modbus" suffix kept for continuity with the entity_ids already
        # deployed on the dashboard (previously a template light platform;
        # this integration replaces that, not the naming).
        slug = f"vertex_{device['device_id']}_modbus"
        self.entity_id = f"light.{slug}"
        self._attr_unique_id = f"{DOMAIN}_{slug}"
        self._attr_name = f"{device['room']}/{device['name']}"
        self._attr_device_info = device_info
        self._last_brightness_pct = 100

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.attributes.get("brightness"):
            self._last_brightness_pct = _brightness_to_pct(last_state.attributes["brightness"])

    def _device_data(self) -> dict:
        return (self.coordinator.data or {}).get(self._device_id, {})

    @property
    def is_on(self) -> bool | None:
        level = self._device_data().get("level_pct")
        return None if level is None else level > 0

    @property
    def brightness(self) -> int | None:
        level = self._device_data().get("level_pct")
        if not level:
            return None
        self._last_brightness_pct = level  # observed from hardware, keeps "restore on" accurate
        return _pct_to_brightness(level)

    @property
    def available(self) -> bool:
        # The device's own status byte (offset +19) does NOT reliably track
        # real communication health -- cross-checked against Vertex's own
        # GeneralStatus.ERROR (via REST /logic/vertex/devicesdali): several
        # devices report status=1 ("offline") here while GeneralStatus shows
        # zero errors and the light is demonstrably on and responsive. A
        # successful Modbus read (this device present in coordinator.data at
        # all) is already sufficient evidence of availability; the status
        # byte is exposed as a diagnostic attribute instead of gating on it.
        if not super().available:
            return False
        return self._device_id in (self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict:
        return {"dali_status": self._device_data().get("status", "unknown")}

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        pct = _brightness_to_pct(brightness) if brightness is not None else self._last_brightness_pct
        pct = max(1, min(100, pct))
        if await self.coordinator.async_write_register(self._write_register, pct):
            self._last_brightness_pct = pct
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        if await self.coordinator.async_write_register(self._write_register, 0):
            await self.coordinator.async_request_refresh()


class VertexGroupLight(CoordinatorEntity, RestoreEntity, LightEntity):
    """A Vertex primary group's command channel -- no independent readback.

    State is self-managed (whatever HA last commanded), not polled --
    confirmed no per-group Input Register exists on this controller.
    """

    _attr_has_entity_name = False
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator, group: dict, device_info: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._write_register = group[CONF_WRITE_REGISTER]
        slug = f"vertex_{group['group_id']}_group_modbus"
        self.entity_id = f"light.{slug}"
        self._attr_unique_id = f"{DOMAIN}_{slug}"
        self._attr_name = f"{group['room']}/{group['name']} Group"
        self._attr_device_info = device_info
        self._is_on = False
        self._brightness_pct = 100

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
            if last_state.attributes.get("brightness"):
                self._brightness_pct = _brightness_to_pct(last_state.attributes["brightness"])

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return _pct_to_brightness(self._brightness_pct)

    @property
    def available(self) -> bool:
        return self.coordinator.controller_online

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        pct = _brightness_to_pct(brightness) if brightness is not None else self._brightness_pct
        pct = max(1, min(100, pct))
        if await self.coordinator.async_write_register(self._write_register, pct):
            self._is_on = True
            self._brightness_pct = pct
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        if await self.coordinator.async_write_register(self._write_register, 0):
            self._is_on = False
            self.async_write_ha_state()
