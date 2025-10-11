"""
Clean Z-Wave JS Server Client

A streamlined client for interacting with Z-Wave JS Server that provides:
- Device discovery and information
- Real-time event monitoring
- Device control commands
- Easy integration with other libraries
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

import aiohttp
from zwave_js_server.client import Client


class ZWaveClient:
    """A clean, reusable Z-Wave JS Server client."""

    def __init__(self, server_url: str):
        """Initialize the Z-Wave client.

        Args:
            server_url: WebSocket URL for the Z-Wave JS Server (e.g., "ws://localhost:3000")
        """
        self.server_url = server_url
        self.client: Optional[Client] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.connected = False
        self.event_handlers: Dict[str, List[Callable]] = {}

    async def connect(self) -> bool:
        """Connect to the Z-Wave JS Server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.session = aiohttp.ClientSession()
            self.client = Client(self.server_url, self.session)

            await self.client.connect()
            await self.client.initialize()

            # Wait for driver to be ready
            driver_ready = asyncio.Event()
            asyncio.create_task(self.client.listen(driver_ready))

            await asyncio.wait_for(driver_ready.wait(), timeout=15.0)

            # Set up event monitoring
            if self.client.driver:
                self._setup_event_monitoring()

            self.connected = True
            return True

        except (ConnectionError, asyncio.TimeoutError, OSError) as e:
            print(f"Connection failed: {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        """Disconnect from the Z-Wave JS Server."""
        if self.client and self.client.connected:
            await self.client.disconnect()
        if self.session:
            await self.session.close()
        self.connected = False

    def get_controller_info(self) -> Dict[str, Any]:
        """Get information about the Z-Wave controller.

        Returns:
            Dictionary with controller information including home_id, sdk_version, etc.
        """
        if not self.client or not self.client.driver:
            return {}

        controller = self.client.driver.controller
        driver = self.client.driver

        info = {
            "home_id": getattr(controller, "home_id", None),
            "own_node_id": getattr(controller, "own_node_id", None),
            "is_secondary": getattr(controller, "is_secondary", None),
            "is_using_home_id_from_other_network": getattr(
                controller, "is_using_home_id_from_other_network", None
            ),
            "is_SIS_present": getattr(controller, "is_SIS_present", None),
            "was_real_primary": getattr(controller, "was_real_primary", None),
            "is_static_update_controller": getattr(
                controller, "is_static_update_controller", None
            ),
            "is_slave": getattr(controller, "is_slave", None),
            "serial_api_version": getattr(controller, "serial_api_version", None),
            "manufacturer_id": getattr(controller, "manufacturer_id", None),
            "product_type": getattr(controller, "product_type", None),
            "product_id": getattr(controller, "product_id", None),
            "supported_function_types": getattr(
                controller, "supported_function_types", None
            ),
            "suc_node_id": getattr(controller, "suc_node_id", None),
            "supports_timers": getattr(controller, "supports_timers", None),
            "sdk_version": getattr(driver, "controller", {})
            and getattr(controller, "sdk_version", None),
            "library_version": getattr(controller, "library_version", None),
            "type": getattr(controller, "type", None),
            "zwaveApiVersion": getattr(controller, "zwaveApiVersion", None),
        }

        # Get a friendly name for the controller type
        if info["type"]:
            info["type_name"] = str(info["type"])
        else:
            info["type_name"] = "Unknown"

        return info

    def get_devices(self) -> Dict[int, Dict[str, Any]]:
        """Get information about all Z-Wave devices.

        Returns:
            Dictionary mapping node IDs to device information
        """
        if not self.client or not self.client.driver:
            return {}

        devices = {}
        nodes = self.client.driver.controller.nodes

        for node_id, node in nodes.items():
            current_value = 0
            for value_id in node.values.values():
                if (
                    hasattr(value_id, "property_name")
                    and value_id.property_name == "currentValue"
                ):
                    current_value = value_id.value
                    break

            devices[node_id] = {
                "id": node_id,
                "name": node.name or f"Node {node_id}",
                "status": self._get_status_name(node.status),
                "manufacturer_id": getattr(node, "manufacturer_id", None),
                "product_type": getattr(node, "product_type", None),
                "firmware_version": getattr(node, "firmware_version", None),
                "device_type": self._get_device_type(node),
                "is_alive": node.status == 4,
                "is_asleep": node.status == 1,
                "current_value": current_value,
            }

        return devices

    async def get_device_properties(self, node_id: int) -> Dict[str, Any]:
        """Get detailed properties for a specific device.

        Args:
            node_id: The Z-Wave node ID

        Returns:
            Dictionary of device properties and values
        """
        if not self.client or not self.client.driver:
            return {}

        node = self.client.driver.controller.nodes.get(node_id)
        if not node:
            return {}

        properties = {}
        try:
            value_ids = await node.async_get_defined_value_ids()
            for value_id in value_ids:
                val = node.values.get(value_id)
                if val and hasattr(val, "prope rty_name"):
                    prop_key = f"{val.command_class_name}.{val.property_name}"
                    properties[prop_key] = {
                        "value": val.value,
                        "writeable": val.metadata.writeable if val.metadata else False,
                        "type": val.metadata.type if val.metadata else "unknown",
                    }
        except (KeyError, AttributeError, ConnectionError) as e:
            print(f"Error getting properties for node {node_id}: {e}")

        return properties

    async def set_device_value(
        self, node_id: int, property_name: str, value: Any
    ) -> bool:
        """Set a value on a Z-Wave device.

        Args:
            node_id: The Z-Wave node ID
            property_name: Property name (e.g., "targetValue", "currentValue")
            value: Value to set

        Returns:
            True if successful, False otherwise
        """
        if not self.client or not self.client.driver:
            return False

        node = self.client.driver.controller.nodes.get(node_id)
        if not node:
            return False

        try:
            for value_id in node.values.values():
                if (
                    hasattr(value_id, "property_name")
                    and value_id.property_name == property_name
                    and value_id.metadata.writeable
                ):
                    await node.async_set_value(value_id, value)
                    return True
            return False
        except (KeyError, AttributeError, ConnectionError, ValueError) as e:
            print(f"Error setting value: {e}")
            return False

    async def turn_on(self, node_id: int) -> bool:
        """Turn on a device (switch/dimmer).

        Args:
            node_id: The Z-Wave node ID

        Returns:
            True if successful, False otherwise
        """
        return await self.set_device_value(node_id, "targetValue", 99)

    async def turn_off(self, node_id: int) -> bool:
        """Turn off a device (switch/dimmer).

        Args:
            node_id: The Z-Wave node ID

        Returns:
            True if successful, False otherwise
        """
        # Try common "off" properties
        return await self.set_device_value(node_id, "targetValue", 0)

    async def set_dimmer_level(self, node_id: int, level: int) -> bool:
        """Set dimmer level (0-99).

        Args:
            node_id: The Z-Wave node ID
            level: Dimmer level (0-99)

        Returns:
            True if successful, False otherwise
        """
        if not 0 <= level <= 100:
            return False
        return await self.set_device_value(node_id, "targetValue", level)

    def add_event_handler(self, event_type: str, handler: Callable):
        """Add an event handler for Z-Wave events.

        Args:
            event_type: Type of event ("value_updated", "node_status_changed", "all")
            handler: Function to call when event occurs
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    def remove_event_handler(self, event_type: str, handler: Callable):
        """Remove an event handler.

        Args:
            event_type: Type of event
            handler: Handler function to remove
        """
        if event_type in self.event_handlers:
            try:
                self.event_handlers[event_type].remove(handler)
            except ValueError:
                pass

    def _setup_event_monitoring(self):
        """Set up event monitoring using the fallback approach."""
        if not self.client or not self.client.driver:
            return

        # Override the driver's receive_event method to catch all events
        original_receive_event = self.client.driver.receive_event

        def enhanced_receive_event(event):
            self._handle_event(event)
            return original_receive_event(event)

        self.client.driver.receive_event = enhanced_receive_event

    def _handle_event(self, event):
        """Handle incoming Z-Wave events."""
        event_type = getattr(event, "type", "")
        event_data = getattr(event, "data", {})

        # Handle value updated events
        if event_type == "value updated":
            self._handle_value_updated(event, event_data)

        # Handle node status events
        elif event_type in ["node alive", "node dead", "node asleep", "node awake"]:
            self._handle_node_status_changed(event, event_data)

        # Call "all" event handlers
        for handler in self.event_handlers.get("all", []):
            try:
                handler(event_type, event_data)
            except (TypeError, AttributeError) as e:
                print(f"Error in event handler: {e}")

    def _handle_value_updated(self, _event, event_data):
        """Handle value updated events."""
        args = event_data.get("args", {})
        node_id = event_data.get("nodeId")

        if node_id:
            event_info = {
                "node_id": node_id,
                "node_name": self._get_node_name(node_id),
                "command_class": args.get("commandClassName", ""),
                "property": args.get("propertyName", ""),
                "property_key": args.get("propertyKeyName", ""),
                "new_value": args.get("newValue"),
                "prev_value": args.get("prevValue"),
            }

            # Call value_updated handlers
            for handler in self.event_handlers.get("value_updated", []):
                try:
                    handler(event_info)
                except (TypeError, AttributeError) as e:
                    print(f"Error in value_updated handler: {e}")

    def _handle_node_status_changed(self, event, event_data):
        """Handle node status change events."""
        node_id = event_data.get("nodeId") or getattr(event, "nodeId", None)

        if node_id:
            event_info = {
                "node_id": node_id,
                "node_name": self._get_node_name(node_id),
                "status": getattr(event, "type", "").replace("node ", ""),
            }

            # Call node_status_changed handlers
            for handler in self.event_handlers.get("node_status_changed", []):
                try:
                    handler(event_info)
                except (TypeError, AttributeError) as e:
                    print(f"Error in node_status_changed handler: {e}")

    def _get_node_name(self, node_id: int) -> str:
        """Get friendly name for a node."""
        if not self.client or not self.client.driver:
            return f"Node {node_id}"

        node = self.client.driver.controller.nodes.get(node_id)
        return node.name if node and node.name else f"Node {node_id}"

    def _get_status_name(self, status: int) -> str:
        """Convert status number to readable name."""
        status_names = {0: "Unknown", 1: "Asleep", 2: "Awake", 3: "Dead", 4: "Alive"}
        return status_names.get(status, f"Status {status}")

    def _get_device_type(self, node) -> str:
        """Get device type description."""
        if hasattr(node, "device_class") and node.device_class:
            if hasattr(node.device_class, "generic") and hasattr(
                node.device_class, "specific"
            ):
                return f"{node.device_class.generic.label} - {node.device_class.specific.label}"
        return "Unknown"
