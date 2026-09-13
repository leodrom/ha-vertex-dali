# vertex_dali

Home Assistant custom integration for controlling Vertex/Glamox/ES-SYSTEM
DALI-2 lighting controllers over Modbus TCP.

## Why

Vertex controllers have a fixed, vendor-documented Modbus register map for
**reading** luminaire state (Analog Input Registers: `base = 400 + short_address
× 50 + dali_port × 3200`, one 50-register block per luminaire). There is no
equivalent fixed map for **writing** — the vendor's own documentation says the
Holding Register used to control a group or luminaire is "configured by the
installer" via a generic Node-RED node that just listens for a write on
whatever register you point it at. So a working setup is: each installer
picks arbitrary, unique register numbers per group/device in their own
Node-RED flow, and this integration is told which register maps to which
name in a compact YAML list.

Earlier setup work here used the built-in `modbus:` platform plus a full copy
of `input_number:`/`automation:`/`template: light:` boilerplate per entity —
correct, but ~40+ lines of YAML per luminaire/group. This integration
replaces all of that with a coordinator + two entity classes, driven by a
YAML list that's just names, addresses and register numbers.

## Features

- One shared `AsyncModbusTcpClient` connection per controller, batching reads
  across "windows" of nearby register addresses (a gap wider than 500
  registers between two rooms starts a new window, so the read cycle doesn't
  waste requests on empty register space).
- Individual luminaire lights: state/brightness read from the polled `ActualLevel`
  register (0-254 DALI log scale, decoded to 0-100%); "turn on" without an
  explicit brightness restores the last known non-zero level.
- Group lights: there is no per-group Input Register on this controller, so a
  group's state is self-managed — whatever Home Assistant last commanded it
  to, persisted across restarts via `RestoreEntity`.
- Device hierarchy: each luminaire's `via_device` points at its own group
  (not the controller directly), so a group's device page lists its member
  luminaires, the same way a Zigbee/Z-Wave hub lists its connected devices.
- YAML stays the source of truth (same pattern as `modbus_meter_eastron`) —
  an import-only config flow just gives each controller a ConfigEntry so
  Home Assistant can own the Device Registry hierarchy.

## Configuration

```yaml
vertex_dali:
  controllers:
    - name: vertex_88a2
      host: 192.168.0.68
      port: 502
      scan_interval: 1
      rooms:
        - name: R01
          groups:
            - name: G01
              write_register: 100
              devices:
                - name: "G01.1"
                  short_address: 4
                  dali_port: 0
                  write_register: 300
```

- `write_register` is the raw 0-based Modbus wire address — whatever your
  installer's Node-RED `vertexmodbus` node is actually wired to. Note that
  the Node-RED node's own "Register" UI field is 1-based, so if the node
  shows `Register: 301`, the wire address (and the value to put here) is `300`.
- `short_address` / `dali_port` are the luminaire's real DALI short address
  and port — used to compute its fixed read register via the formula above.
- Groups don't have `short_address`/`dali_port` (no read register exists for
  them) — only a `write_register`.

## License

MIT
