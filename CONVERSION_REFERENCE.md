# Quick Reference: Class and Function Mapping

## Class Renaming

| Old (Lutron) | New (Z-Wave) | File |
|--------------|--------------|------|
| `LutronConfig` | `ZWaveConfig` | config.py |
| `LutronLightInfo` | `ZWaveLightInfo` | const.py |
| `LutronCoverInfo` | `ZWaveCoverInfo` | const.py |
| `LutronSceneInfo` | `ZWaveSceneInfo` | const.py |
| `LutronLight` | `ZWaveLight` | light.py |
| `LutronButton` | `ZWaveButton` | button.py |
| `ZeroconfScanner` | `ZWaveDiscovery` | discover.py |
| `ZeroconfService` | `ZWaveServer` | discover.py |

## Communication Layer

| Lutron | Z-Wave | Purpose |
|--------|--------|---------|
| `Smartbridge` | `ZWaveClient` | Main communication class |
| `async_pair()` | Not needed | Authentication/pairing |
| Certificate files | Not needed | Authentication |
| `get_devices_by_domain("light")` | `get_devices()` + filtering | Device discovery |
| `turn_on(device_id)` | `turn_on(node_id)` | Turn on device |
| `turn_off(device_id)` | `turn_off(node_id)` | Turn off device |
| `set_value(device_id, value)` | `set_dimmer_level(node_id, level)` | Set brightness |
| `add_subscriber()` | `add_event_handler()` | Event monitoring |

## Configuration Fields

### Connection
- **Lutron:** IP address (e.g., `192.168.1.100`)
- **Z-Wave:** WebSocket URL (e.g., `ws://192.168.1.100:3000`)

### Device Identifier
- **Lutron:** `device_id` (string from bridge)
- **Z-Wave:** `node_id` (integer Z-Wave node ID)

### Brightness Scale
- **Lutron:** 0-100
- **Z-Wave:** 0-100 internally, 0-255 for UC API

## File Status

### Fully Converted ✓
- [x] const.py
- [x] config.py
- [x] bridge.py (core functionality)
- [x] light.py
- [x] button.py
- [x] driver.py
- [x] discover.py
- [x] setup.py
- [x] driver.json
- [x] README.md
- [x] requirements.txt

### Partially Implemented
- [ ] Scenes (structure exists, implementation needed)
- [ ] Covers (structure exists, Z-Wave specifics needed)

### Not Yet Implemented
- [ ] Advanced Z-Wave features (node management, configuration parameters)
- [ ] Additional device types (sensors, locks, thermostats)
- [ ] Z-Wave network management

## Important Code Patterns

### Device Discovery
```python
# Lutron
lights = smartbridge.get_devices_by_domain("light")

# Z-Wave
devices = zwave_client.get_devices()
for node_id, device_info in devices.items():
    if "switch" in device_type or "dimmer" in device_type:
        # It's a light/switch
```

### Brightness Control
```python
# Lutron (0-100 scale)
await smartbridge.set_value(device_id, brightness)

# Z-Wave (convert from 0-255 to 0-100)
zwave_brightness = int(brightness * 100 / 255)
await zwave_client.set_dimmer_level(node_id, zwave_brightness)
```

### Event Handling
```python
# Lutron
smartbridge.add_subscriber(device_id, callback)

# Z-Wave
zwave_client.add_event_handler('value_updated', callback)
zwave_client.add_event_handler('node_status_changed', callback)
```

## Testing Checklist

- [ ] Connection to Z-Wave JS Server
- [ ] Device discovery
- [ ] Turn lights on/off
- [ ] Brightness adjustment
- [ ] State synchronization
- [ ] Reconnection after disconnect
- [ ] Multiple devices
- [ ] Entity availability states
