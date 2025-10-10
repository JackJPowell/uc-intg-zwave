[![Discord](https://badgen.net/discord/onli### Prerequisites

- A running [Z-Wave JS Server](https://github.com/zwave-js/zwave-js-server) instance
- Your Z-Wave JS Server WebSocket URL (e.g., `ws://192.168.1.100:3000`)

### Unfolded Circle Remote

1. **Download** the latest `.tar.gz` release from the [Releases](https://github.com/JackJPowell/uc-intg-zwave/releases) page.
2. **Upload** the file via the Integrations tab in your remote's web configurator (requires firmware >= 2.0.0).embers/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Release](https://img.shields.io/github/v/release/jackjpowell/uc-intg-zwave)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/jackjpowell/uc-intg-zwave/total)
![Maintenance](https://img.shields.io/maintenance/yes/2025.svg)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee☕-FFDD00?logo=buy-me-a-coffee&logoColor=white&labelColor=grey)](https://buymeacoffee.com/jackpowell)

# Z-Wave Integration for Unfolded Circle Remotes

Easily control your Z-Wave devices directly from your Unfolded Circle Remote via Z-Wave JS Server. Powered by [uc-integration-api](https://github.com/aitatoi/integration-python-library).

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
  - [Unfolded Circle Remote](#unfolded-circle-remote)
  - [Docker](#docker)
  - [Docker Compose](#docker-compose)
- [Setup & Configuration](#setup--configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

---

## Features

- **Lights & Switches:**  
  - Toggle on/off  
  - Adjust brightness (for dimmers)  
  - View state  

- **Future Plans:**  
  - Support for Z-Wave scenes
  - Support for Cover entities (shades, blinds)
  - Support for sensors and other Z-Wave devices

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

## Setup & Configuration

After installation, open the integration in your remote’s web interface:

1. **Scan for Hubs:** The integration will automatically search for Zwave devices on your network.
2. **Manual Entry:** Optionally, you can enter your hub’s IP address manually.
3. **Pairing:** Press the small black button on the back of your hub to complete pairing when prompted.

---

## Troubleshooting

- **Hub not detected?**  
  Ensure your hub and remote are on the same network / vlan. Try manual IP entry.

- **Pairing fails?**  
  The setup process has a short timeout so make sure you are ready to press the button after pressing next. 

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
