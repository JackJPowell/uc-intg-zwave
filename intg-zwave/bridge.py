"""
This module implements the Z-Wave communication of the Remote Two/3 integration driver.

"""

import logging
from asyncio import AbstractEventLoop
from typing import Any

from const import ZWaveCoverInfo, ZWaveDevice, ZWaveLightInfo
from ucapi import EntityTypes
from ucapi.cover import Attributes as CoverAttr
from ucapi.light import Attributes as LightAttr
from ucapi.media_player import Attributes as MediaAttr
from ucapi_framework import DeviceEvents, ExternalClientDevice, create_entity_id
from zwave_client import ZWaveClient

_LOG = logging.getLogger(__name__)


class SmartHub(ExternalClientDevice):
    """Representing a Z-Wave Controller."""

    def __init__(
        self,
        config: ZWaveDevice,
        loop: AbstractEventLoop | None = None,
        config_manager=None,
        watchdog_interval: int = 30,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 3,
    ) -> None:
        """Create instance."""
        super().__init__(
            device_config=config,
            loop=loop,
            config_manager=config_manager,
            watchdog_interval=watchdog_interval,
            reconnect_delay=reconnect_delay,
            max_reconnect_attempts=max_reconnect_attempts,
        )
        self._lights: list[ZWaveLightInfo] = []
        self._covers: list[ZWaveCoverInfo] = []

    # ─────────────────────────────────────────────────────────────────
    # Properties (required by BaseDeviceInterface)
    # ─────────────────────────────────────────────────────────────────

    @property
    def identifier(self) -> str:
        """Return the device identifier."""
        if not self._device_config.identifier:
            raise ValueError("Instance not initialized, no identifier available")
        return self._device_config.identifier

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return self._device_config.identifier

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device_config.name

    @property
    def address(self) -> str | None:
        """Return the optional device address."""
        return self._device_config.address

    # ─────────────────────────────────────────────────────────────────
    # Additional Properties
    # ─────────────────────────────────────────────────────────────────

    @property
    def device_config(self) -> ZWaveDevice:
        """Return the device configuration."""
        return self._device_config

    @property
    def state(self) -> str:
        """Return the device state."""
        return "ON" if self.is_connected else "OFF"

    @property
    def attributes(self) -> dict[str, Any]:
        """Return the device attributes."""
        return {
            MediaAttr.STATE: self.state,
        }

    @property
    def lights(self) -> list[ZWaveLightInfo]:
        """Return the list of light entities."""
        return self._lights

    @property
    def covers(self) -> list[ZWaveCoverInfo]:
        """Return the list of cover entities."""
        return self._covers

    # ─────────────────────────────────────────────────────────────────
    # ExternalClientDevice Implementation
    # ─────────────────────────────────────────────────────────────────

    async def create_client(self) -> ZWaveClient:
        """Create the Z-Wave client instance."""
        return ZWaveClient(self._device_config.address)

    async def connect_client(self) -> None:
        """Connect the Z-Wave client and set up event handlers."""
        success = await self._client.connect()
        if not success:
            raise ConnectionError("Failed to connect to Z-Wave controller")

        # Set up event handlers
        self._setup_event_handlers()
        _LOG.info("🏠 BRIDGE [%s]: Connected to Z-Wave controller", self.log_id)

    async def disconnect_client(self) -> None:
        """Disconnect the Z-Wave client and remove event handlers."""
        self._remove_event_handlers()
        await self._client.disconnect()

    def check_client_connected(self) -> bool:
        """Check if the Z-Wave client is connected."""
        return self._client is not None and self._client.connected

    # ─────────────────────────────────────────────────────────────────
    # Event Handlers
    # ─────────────────────────────────────────────────────────────────

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for Z-Wave events."""
        self._client.add_event_handler("value_updated", self._on_value_updated)
        self._client.add_event_handler(
            "node_status_changed", self._on_node_status_changed
        )

    def _remove_event_handlers(self) -> None:
        """Remove event handlers for Z-Wave events."""
        if self._client:
            self._client.remove_event_handler("value_updated", self._on_value_updated)
            self._client.remove_event_handler(
                "node_status_changed", self._on_node_status_changed
            )

    def _on_value_updated(self, event_info: dict) -> None:
        """Handle Z-Wave value updated events."""
        try:
            node_id = event_info.get("node_id")

            if node_id is None:
                _LOG.warning(
                    "⚠️  [%s] Received value update with no node_id: %s",
                    self.log_id,
                    event_info,
                )
                return

            # Validate node_id is numeric
            if not isinstance(node_id, int):
                _LOG.error(
                    "❌ [%s] node_id is not an integer: %s (type: %s)",
                    self.log_id,
                    node_id,
                    type(node_id).__name__,
                )
                return

            _LOG.debug(
                "⚡ BRIDGE [%s]: Value updated - node %d",
                self.log_id,
                node_id,
            )

            # Check if it's a light or cover and update accordingly
            is_light = any(light.node_id == node_id for light in self._lights)
            is_cover = any(cover.node_id == node_id for cover in self._covers)

            if is_light:
                self._update_light(node_id, event_info)
            elif is_cover:
                self._update_cover(node_id, event_info)
            else:
                _LOG.debug(
                    "[%s] Node %d is not a known light or cover, ignoring update",
                    self.log_id,
                    node_id,
                )

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "❌ [%s] Error handling value update: %s",
                self.log_id,
                ex,
                exc_info=True,
            )

    def _on_node_status_changed(self, event_info: dict) -> None:
        """Handle Z-Wave node status changed events."""
        _LOG.debug("[%s] Node status changed: %s", self.log_id, event_info)

    # ─────────────────────────────────────────────────────────────────
    # Controller Info
    # ─────────────────────────────────────────────────────────────────

    def get_controller_info(self) -> dict[str, Any]:
        """Get information about the Z-Wave controller.

        Returns dictionary with home_id, sdk_version, library_version, etc.
        """
        if not self._client or not self._client.connected:
            return {}

        return self._client.get_controller_info()

    # ─────────────────────────────────────────────────────────────────
    # Light Operations
    # ─────────────────────────────────────────────────────────────────

    def _update_light(self, node_id: int, event_info: dict = None) -> None:
        """Update light state in cache and emit update event."""
        update = {}
        try:
            # Find the light using comprehension
            light = next(
                (entity for entity in self._lights if entity.node_id == node_id), None
            )

            if not light:
                _LOG.debug("[%s] Light not found for node_id: %s", self.log_id, node_id)
                return

            # Update the light's state from event_info if available
            if event_info:
                # Extract and validate new_value
                new_value = event_info.get("new_value")

                # Validate that new_value is numeric (int or float)
                if new_value is None:
                    _LOG.warning(
                        "⚠️  [%s] new_value is None for light node_id=%s, skipping update",
                        self.log_id,
                        node_id,
                    )
                    return

                if isinstance(new_value, dict):
                    _LOG.debug(
                        "❌ [%s] new_value is a dict for light node_id=%s, expected int/float. Data: %s",
                        self.log_id,
                        node_id,
                        new_value,
                    )
                    return

                if not isinstance(new_value, (int, float)):
                    _LOG.error(
                        "❌ [%s] new_value has invalid type %s for light node_id=%s, expected int/float. Value: %s",
                        self.log_id,
                        type(new_value).__name__,
                        node_id,
                        new_value,
                    )
                    return

                # Validate range (0-100 for Z-Wave)
                if not (0 <= new_value <= 100):
                    _LOG.warning(
                        "⚠️  [%s] Brightness value %s out of range [0-100] for light node_id=%s, clamping",
                        self.log_id,
                        new_value,
                        node_id,
                    )
                    new_value = max(0, min(100, new_value))

                # Update light state
                light.brightness = 0
                _LOG.debug("Event Info: %s", new_value)
                if new_value > 0:
                    light.brightness = new_value * 255 / 100
                light.current_state = light.brightness

                _LOG.debug(
                    "[%s] Updated light cache: node_id=%s, state=%s, brightness=%s",
                    self.log_id,
                    node_id,
                    light.current_state,
                    light.brightness,
                )

            # Prepare update event
            update[LightAttr.STATE] = "ON" if light.current_state > 0 else "OFF"
            update[LightAttr.BRIGHTNESS] = light.brightness

            self.events.emit(
                DeviceEvents.UPDATE,
                create_entity_id(
                    EntityTypes.LIGHT,
                    self._device_config.identifier,
                    str(light.node_id),
                ),
                update,
            )

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Light update: protocol error", self.log_id)

    async def get_lights(self) -> list[Any]:
        """Return the list of light entities from Z-Wave network."""
        if not self._client or not self._client.connected:
            await self.connect()

        devices = self._client.get_devices()
        light_list = []

        for node_id, device_info in devices.items():
            # Check if device is a light/dimmer (this is a simplified check)
            device_type = device_info.get("device_type", "").lower()
            if (
                "switch" in device_type
                or "dimmer" in device_type
                or "multilevel" in device_type
            ) and "motor control" not in device_type:
                light_list.append(
                    ZWaveLightInfo(
                        device_id=str(node_id),
                        node_id=node_id,
                        current_state=device_info.get("current_value", 0),
                        brightness=device_info.get("current_value", 0),
                        type=device_type,
                        name=device_info.get("name", f"Node {node_id}"),
                        model=device_info.get("device_type", "Unknown"),
                    )
                )

        # Update internal lights list
        self._lights = light_list
        return light_list

    async def control_light(self, light_id: str, brightness: int) -> None:
        """Control a light with a specific brightness."""
        update = {}
        try:
            node_id = int(light_id)
            if brightness == 0:
                await self._client.turn_off(node_id)
            elif brightness == 99:
                await self._client.turn_on(node_id)
            else:
                await self._client.set_dimmer_level(node_id, brightness)

            update[LightAttr.STATE] = "ON" if brightness > 0 else "OFF"
            update[LightAttr.BRIGHTNESS] = (
                100 if brightness == 99 else brightness * 255 / 100
            )

            self.events.emit(
                DeviceEvents.UPDATE,
                create_entity_id(
                    EntityTypes.LIGHT,
                    self._device_config.identifier,
                    light_id,
                ),
                update,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error turning on light %s: %s", self.log_id, light_id, err)

    async def toggle_light(self, light_id: str) -> None:
        """Toggle a light."""
        try:
            # Get current state from lights list
            light = next(
                (
                    light_entity
                    for light_entity in self._lights
                    if str(light_entity.node_id) == light_id
                ),
                None,
            )
            if light:
                is_on = light.current_state > 0
                node_id = int(light_id)
                if is_on:
                    await self._client.turn_off(node_id)
                else:
                    await self._client.turn_on(node_id)
                self.events.emit(
                    DeviceEvents.UPDATE,
                    create_entity_id(
                        EntityTypes.LIGHT,
                        self._device_config.identifier,
                        light_id,
                    ),
                    {
                        LightAttr.STATE: "OFF" if is_on else "ON",
                        LightAttr.BRIGHTNESS: 0 if is_on else 255,
                    },
                )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error toggling light %s: %s", self.log_id, light_id, err)

    # ─────────────────────────────────────────────────────────────────
    # Cover Operations
    # ─────────────────────────────────────────────────────────────────

    def _update_cover(self, node_id: int, event_info: dict = None) -> None:
        """Update cover state in cache and emit update event."""
        update = {}
        try:
            # Find the cover using comprehension
            cover = next(
                (entity for entity in self._covers if entity.node_id == node_id), None
            )

            if not cover:
                _LOG.debug("[%s] Cover not found for node_id: %s", self.log_id, node_id)
                return

            # Update the cover's state from event_info if available
            if event_info:
                # Extract and validate new_value
                new_value = event_info.get("new_value")

                # Validate that new_value is numeric (int or float)
                if new_value is None:
                    _LOG.warning(
                        "⚠️  [%s] new_value is None for cover node_id=%s, skipping update",
                        self.log_id,
                        node_id,
                    )
                    return

                if isinstance(new_value, dict):
                    _LOG.error(
                        "❌ [%s] new_value is a dict for cover node_id=%s, expected int/float. Data: %s",
                        self.log_id,
                        node_id,
                        new_value,
                    )
                    return

                if not isinstance(new_value, (int, float)):
                    _LOG.error(
                        "❌ [%s] new_value has invalid type %s for cover node_id=%s, expected int/float. Value: %s",
                        self.log_id,
                        type(new_value).__name__,
                        node_id,
                        new_value,
                    )
                    return

                # Validate range (0-100 for position)
                if not (0 <= new_value <= 100):
                    _LOG.warning(
                        "⚠️  [%s] Cover position value %s out of range [0-100] for node_id=%s, clamping",
                        self.log_id,
                        new_value,
                        node_id,
                    )
                    new_value = max(0, min(100, new_value))

                # Update cover state
                cover.position = new_value
                cover.current_state = cover.position

                _LOG.debug(
                    "[%s] Updated cover cache: node_id=%s, position=%s",
                    self.log_id,
                    node_id,
                    cover.position,
                )

            # Prepare update event
            update[CoverAttr.STATE] = "OPEN" if cover.position > 50 else "CLOSED"
            update[CoverAttr.POSITION] = 100 if cover.position == 99 else cover.position

            self.events.emit(
                DeviceEvents.UPDATE,
                create_entity_id(
                    EntityTypes.COVER,
                    self._device_config.identifier,
                    str(cover.node_id),
                ),
                update,
            )

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Cover update: protocol error", self.log_id)

    async def get_covers(self) -> list[Any]:
        """Return the list of cover entities from Z-Wave network."""
        if not self._client or not self._client.connected:
            await self.connect()

        devices = self._client.get_devices()
        cover_list = []

        for node_id, device_info in devices.items():
            # Check if device is a cover/shade/blind (this is a simplified check)
            device_type = device_info.get("device_type", "").lower()
            if (
                "cover" in device_type
                or "blind" in device_type
                or "shade" in device_type
                or "curtain" in device_type
                or "window covering" in device_type
                or "motor control" in device_type
            ):
                cover_list.append(
                    ZWaveCoverInfo(
                        device_id=str(node_id),
                        node_id=node_id,
                        current_state=device_info.get("current_value", 0),
                        position=device_info.get("current_value", 0),
                        type=device_type,
                        name=device_info.get("name", f"Node {node_id}"),
                        model=device_info.get("device_type", "Unknown"),
                    )
                )

        # Update internal covers list
        self._covers = cover_list
        return cover_list

    async def control_cover(self, cover_id: str, position: int) -> None:
        """Control a cover to a specific position (0-100)."""
        update = {}
        try:
            node_id = int(cover_id)
            # Position: 0 = closed, 100 = open
            await self._client.set_dimmer_level(node_id, position)

            # Determine state based on position
            if position <= 5:
                state = "CLOSED"
            elif position >= 95:
                state = "OPEN"
            else:
                state = "OPENING" if position > 50 else "CLOSING"

            update[CoverAttr.STATE] = state
            update[CoverAttr.POSITION] = position

            self.events.emit(
                DeviceEvents.UPDATE,
                create_entity_id(
                    EntityTypes.COVER,
                    self._device_config.identifier,
                    cover_id,
                ),
                update,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "[%s] Error controlling cover %s: %s", self.log_id, cover_id, err
            )

    async def stop_cover(self, cover_id: str) -> None:
        """Stop a cover at its current position."""
        try:
            node_id = int(cover_id)
            # For stop, we need to check current position and keep it
            await self.get_covers()
            cover = next(
                (entity for entity in self._covers if entity.node_id == node_id), None
            )
            if cover:
                # Send the current position to stop movement
                await self._client.set_dimmer_level(node_id, cover.position)
                _LOG.debug(
                    "[%s] Stopped cover %s at position %s",
                    self.log_id,
                    cover_id,
                    cover.position,
                )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error stopping cover %s: %s", self.log_id, cover_id, err)
