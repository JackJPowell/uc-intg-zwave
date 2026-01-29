[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Release](https://img.shields.io/github/v/release/jackjpowell/uc-intg-zwave)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/jackjpowell/uc-intg-zwave/total)
<a href="#"><img src="https://img.shields.io/maintenance/yes/2026.svg"></a>
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee&nbsp;☕-FFDD00?logo=buy-me-a-coffee&logoColor=white&labelColor=grey)](https://buymeacoffee.com/jackpowell)


# Z-Wave Integration for Unfolded Circle Remotes

Control your Z-Wave devices directly from your Unfolded Circle Remote via **Z-Wave JS Server**. This integration features dynamic entity registration, automatic reconnection, and comprehensive device support. Powered by [uc-integration-api](https://github.com/aitatoi/integration-python-library).

---

## Table of Contents
- [Supported Devices](#supported-devices)
- [Installation](#installation)
  - [Unfolded Circle Remote](#unfolded-circle-remote)
  - [Docker](#docker)
  - [Docker Compose](#docker-compose)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

---

## Supported Devices

### Lights & Switches 💡
- ✅ On/Off control
- ✅ Brightness/dimming (0-100%)
- ✅ Real-time state updates
- ✅ Multi-level switches

### Covers 🪟
- ✅ Open/Close/Stop commands
- ✅ Position control (0-100%)
- ✅ State tracking (opening/closing/stopped)
- ✅ Supports: blinds, shades, garage doors, etc.

### Future Support 🔮
- Sensors (temperature, motion, door/window)

---

## Installation

### Unfolded Circle Remote

1. **Download** the latest `.tar.gz` release from the [Releases](https://github.com/JackJPowell/uc-intg-zwave/releases) page.
2. **Upload** the file via the Integrations tab in your remote’s web configurator (requires firmware >= 2.0.0).

### Docker

```sh
docker run -d \
  --name=uc-intg-zwave \
  --network host \
  -v $(pwd)/<local_directory>:/config \
  --restart unless-stopped \
  ghcr.io/jackjpowell/uc-intg-zwave:latest
```

### Docker Compose

```yaml
services:
  uc-intg-zwave:
    image: ghcr.io/jackjpowell/uc-intg-zwave:latest
    container_name: uc-intg-zwave
    network_mode: host
    volumes:
      - ./<local_directory>:/config
    environment:
      - UC_INTEGRATION_HTTP_PORT=9090   # Optional: set custom HTTP port
    restart: unless-stopped
```

---

## Troubleshooting

- **Hub not detected?**  
  Ensure your hub and remote are on the same network / vlan.

- **Need more help?**  
  Reach out on [Discord](https://discord.gg/zGVYf58) or open a [GitHub Issue](https://github.com/JackJPowell/uc-intg-zwave/issues).

---

## Contributing

Contributions are welcome! Please open an issue or pull request.  
See [CONTRIBUTING.md](CONTRIBUTING.md) if available.

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Support

- **Discord:** [Join the community](https://discord.gg/zGVYf58)
- **Buy Me a Coffee:** [Support the project](https://buymeacoffee.com/jackpowell)
- **GitHub Issues:** [Report bugs or request features](https://github.com/JackJPowell/uc-intg-zwave/issues)

---
