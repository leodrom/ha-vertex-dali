"""Per-controller Modbus polling for vertex_dali.

One AsyncModbusTcpClient per Vertex controller, shared by every light entity
on it (both for the coordinator's own reads and for entities' writes -- the
controller only accepts write via Holding Registers through Node-RED's
`vertexmodbus` "listen for register change" nodes, which is a completely
separate mechanism from the read side, but both ride the same TCP session).

Read side has a fixed vendor formula (see const.py, confirmed against 3
independent sources -- memory.ai/vertex-individual-control.md). Write side
has no vendor formula; each group/device's holding register is whatever was
assigned when its `vertexmodbus` node was created in Node-RED, and is listed
explicitly in YAML (config_schema.py).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    OFFSET_PACKED_LEVEL,
    OFFSET_STATUS,
    PORT_STRIDE,
    READ_BLOCK_WORDS,
    REGISTER_BASE,
    REGISTER_STRIDE,
)

_LOGGER = logging.getLogger(__name__)

STATUS_MAP = {0: "stale", 1: "offline", 2: "ok"}
MAX_READ_WORDS = 125  # pymodbus/Modbus TCP hard limit per request
GAP_SPLIT_THRESHOLD = 500  # don't bother reading register ranges wider than this with nothing in them


def read_address(short_address: int, dali_port: int) -> int:
    return REGISTER_BASE + short_address * REGISTER_STRIDE + dali_port * PORT_STRIDE


def decode_level(raw: int) -> int:
    """Raw DALI 0-254 log scale -> 0-100%, same curve used by the Vertex UI."""
    if raw <= 0:
        return 0
    return round((10 ** (((raw - 1) / 253 * 3) - 3)) * 100)


class VertexDaliCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls every luminaire's Actual Level + Status on one Vertex controller."""

    def __init__(self, hass: HomeAssistant, controller: dict, devices: list[dict]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"vertex_dali_{controller['name']}",
            update_interval=timedelta(seconds=controller["scan_interval"]),
        )
        self.controller_name = controller["name"]
        self._host = controller["host"]
        self._port = controller["port"]
        self._timeout = controller["timeout"]
        self._retries = controller["retries"]
        self.devices = devices  # flattened, see config_schema.flatten_devices()
        self._client: AsyncModbusTcpClient | None = None
        self._write_lock = asyncio.Lock()
        self._read_windows = self._build_read_windows()
        self.controller_online = True

    def _build_read_windows(self) -> list[tuple[int, int]]:
        """Coalesce every device's read address into contiguous [start, count] windows.

        Splits on gaps wider than GAP_SPLIT_THRESHOLD so two far-apart rooms
        don't force one giant read spanning empty register space between them.
        """
        addrs = sorted(
            read_address(d["short_address"], d["dali_port"]) for d in self.devices
        )
        if not addrs:
            return []
        windows: list[list[int]] = [[addrs[0], addrs[0] + READ_BLOCK_WORDS]]
        for a in addrs[1:]:
            end = a + READ_BLOCK_WORDS
            if a - windows[-1][1] <= GAP_SPLIT_THRESHOLD:
                windows[-1][1] = max(windows[-1][1], end)
            else:
                windows.append([a, end])
        out = []
        for start, end in windows:
            out.append((start, end - start))
        return out

    async def async_shutdown(self) -> None:
        if self._client is not None:
            self._client.close()
        await super().async_shutdown()

    async def _ensure_connected(self) -> bool:
        if self._client is None:
            self._client = AsyncModbusTcpClient(
                self._host, port=self._port, timeout=self._timeout, retries=self._retries, name=self.controller_name
            )
        if not self._client.connected:
            return await self._client.connect()
        return True

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        if not await self._ensure_connected():
            _LOGGER.warning(
                "vertex_dali: controller %s (%s:%s) unreachable", self.controller_name, self._host, self._port
            )
            self.controller_online = False
            return {}

        self.controller_online = True
        raw_regs: dict[int, int] = {}
        async with self._write_lock:  # keep reads and writes off the wire at the same time
            for start, count in self._read_windows:
                offset = 0
                while offset < count:
                    chunk = min(MAX_READ_WORDS, count - offset)
                    addr = start + offset
                    try:
                        response = await self._client.read_input_registers(addr, count=chunk)
                    except (ModbusException, OSError, asyncio.TimeoutError) as err:
                        _LOGGER.warning(
                            "vertex_dali: %s read failed at %s..%s: %s: %s",
                            self.controller_name, addr, addr + chunk, type(err).__name__, err,
                        )
                        offset += chunk
                        continue
                    if response is None or response.isError():
                        offset += chunk
                        continue
                    for i, value in enumerate(response.registers):
                        raw_regs[addr + i] = value
                    offset += chunk

        results: dict[str, dict[str, Any]] = {}
        for device in self.devices:
            base = read_address(device["short_address"], device["dali_port"])
            packed = raw_regs.get(base + OFFSET_PACKED_LEVEL)
            status_raw = raw_regs.get(base + OFFSET_STATUS)
            if packed is None or status_raw is None:
                continue
            results[device["device_id"]] = {
                "level_pct": decode_level(packed & 0xFF),
                "status": STATUS_MAP.get(status_raw, "unknown"),
            }
        return results

    async def async_write_register(self, address: int, value: int) -> bool:
        """Write one holding register (a group's or device's command channel)."""
        if not await self._ensure_connected():
            return False
        async with self._write_lock:
            try:
                response = await self._client.write_register(address, value)
            except (ModbusException, OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "vertex_dali: %s write failed at register %s: %s: %s",
                    self.controller_name, address, type(err).__name__, err,
                )
                return False
        if response is None or response.isError():
            _LOGGER.warning("vertex_dali: %s write to register %s rejected", self.controller_name, address)
            return False
        return True
