"""Discovery module for Z-Wave JS Server."""

import asyncio
from dataclasses import dataclass
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf, AsyncServiceInfo
from zeroconf import ServiceStateChange, IPVersion


@dataclass
class ZWaveServer:
    """Represents a Z-Wave JS Server instance."""

    address: str


class ZWaveDiscovery:
    """Z-Wave JS Server discovery scanner."""

    def __init__(self, service_type="_zwave-js-server._tcp.local."):
        self.service_type = service_type
        self.found_services = [ZWaveServer]

    async def on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Added:
            info = AsyncServiceInfo(service_type, name)
            await info.async_request(zeroconf, timeout=2000)
            if info.parsed_addresses():
                self.found_services.append(
                    ZWaveServer(
                        address=info.parsed_addresses(version=IPVersion.V4Only)[0]
                    )
                )

    async def scan(self, timeout=2):
        self.found_services = []
        async with AsyncZeroconf() as azc:

            def handler(**kwargs):
                asyncio.create_task(self.on_service_state_change(**kwargs))

            AsyncServiceBrowser(azc.zeroconf, self.service_type, handlers=[handler])
            await asyncio.sleep(timeout)
        return self.found_services
