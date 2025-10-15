"""
This module implements the Z-Wave communication of the Remote Two/3 integration driver.

"""

import asyncio
import logging
from asyncio import AbstractEventLoop
from enum import StrEnum, IntEnum
from typing import Any, ParamSpec, TypeVar

from zwave_client import ZWaveClient
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr
from ucapi import EntityTypes
from config import ZWaveConfig, create_entity_id
from const import ZWaveLightInfo, ZWaveCoverInfo

_LOG = logging.getLogger(__name__)


class EVENTS(IntEnum):
    """Internal driver events."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    PAIRED = 3
    ERROR = 4
    UPDATE = 5


_ZWaveDeviceT = TypeVar("_ZWaveDeviceT", bound="ZWaveConfig")
_P = ParamSpec("_P")


class PowerState(StrEnum):
    """Playback state for companion protocol."""

    OFF = "OFF"
    ON = "ON"
    STANDBY = "STANDBY"


class SmartHub:
    """Representing a Z-Wave Controller."""

    def __init__(
        self, config: ZWaveConfig, loop: AbstractEventLoop | None = None
    ) -> None:
        """Create instance."""
        self._loop: AbstractEventLoop = loop or asyncio.get_running_loop()
        self.events = AsyncIOEventEmitter(self._loop)
        self._is_connected: bool = False
        self._config: ZWaveConfig | None = config
        self._zwave_client: ZWaveClient = ZWaveClient(self._config.address)
        self._connection_attempts: int = 0
        self._state: PowerState = PowerState.OFF
        self._features: dict = {}
        self._lights: list = [ZWaveLightInfo]
        self._covers: list = [ZWaveCoverInfo]
        self._watchdog_task: asyncio.Task | None = None
        self._watchdog_running: bool = False
        self._reconnect_delay: int = 5  # seconds between reconnection attempts
        self._watchdog_interval: int = 30  # seconds between connection checks

    @property
    def device_config(self) -> ZWaveConfig:
        """Return the device configuration."""
        return self._config

    @property
    def identifier(self) -> str:
        """Return the device identifier."""
        if not self._config.identifier:
            raise ValueError("Instance not initialized, no identifier available")
        return self._config.identifier

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return self.device_config.identifier

    @property
    def name(self) -> str:
        """Return the device name."""
        return self.device_config.name

    @property
    def address(self) -> str | None:
        """Return the optional device address."""
        return self.device_config.address

    @property
    def state(self) -> PowerState | None:
        """Return the device state."""
        return "ON" if self._is_connected else "OFF"

    @property
    def attributes(self) -> dict[str, any]:
        """Return the device attributes."""
        updated_data = {
            MediaAttr.STATE: self.state,
        }
        return updated_data

    @property
    def lights(self) -> list[ZWaveLightInfo]:
        """Return the list of light entities."""
        return self._lights

    @property
    def covers(self) -> list[ZWaveCoverInfo]:
        """Return the list of cover entities."""
        return self._covers

    @property
    def is_connected(self) -> bool:
        """Return if the device is connected."""
        return self._is_connected

    def get_controller_info(self) -> dict[str, Any]:
        """Get information about the Z-Wave controller.

        Returns dictionary with home_id, sdk_version, library_version, etc.
        """
        if not self._zwave_client or not self._zwave_client.connected:
            return {}

        return self._zwave_client.get_controller_info()

    async def connect(self) -> bool:
        """Establish connection to the Z-Wave controller."""
        if self._zwave_client.connected:
            return True

        await self.disconnect()
        _LOG.debug("[%s] Connecting to Z-Wave controller", self.log_id)
        self.events.emit(EVENTS.CONNECTING, self.device_config.identifier)

        try:
            success = await self._zwave_client.connect()
            if not success:
                return False

            self._is_connected = True
            self._state = PowerState.ON
            _LOG.info("🏠 BRIDGE [%s]: Connected to Z-Wave controller", self.log_id)

            # Set up event handlers
            self._setup_event_handlers()

            # Start the connection watchdog
            self._start_watchdog()

        except asyncio.CancelledError as err:
            _LOG.error("[%s] Connection cancelled: %s", self.log_id, err)
            return False
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Could not connect: %s", self.log_id, err)
            return False
        finally:
            _LOG.debug("[%s] Connect setup finished", self.log_id)

        self.events.emit(EVENTS.CONNECTED, self.device_config.identifier)
        _LOG.debug("[%s] Connected", self.log_id)

        return True

    async def disconnect(self) -> None:
        """Disconnect from the Z-Wave controller."""
        _LOG.debug("[%s] Disconnecting from Z-Wave controller", self.log_id)

        # Remove event handlers before disconnecting
        self._remove_event_handlers()

        await self._zwave_client.disconnect()
        self._is_connected = False
        self._state = PowerState.OFF
        self.events.emit(EVENTS.DISCONNECTED, self.device_config.identifier)

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for Z-Wave events."""
        self._zwave_client.add_event_handler("value_updated", self._on_value_updated)
        self._zwave_client.add_event_handler(
            "node_status_changed", self._on_node_status_changed
        )

    def _remove_event_handlers(self) -> None:
        """Remove event handlers for Z-Wave events."""
        self._zwave_client.remove_event_handler("value_updated", self._on_value_updated)
        self._zwave_client.remove_event_handler(
            "node_status_changed", self._on_node_status_changed
        )

    def _start_watchdog(self) -> None:
        """Start the connection watchdog."""
        if not self._watchdog_running:
            _LOG.debug("[%s] Starting connection watchdog", self.log_id)
            self._watchdog_running = True
            self._watchdog_task = self._loop.create_task(self._watchdog_loop())

    async def _stop_watchdog(self) -> None:
        """Stop the connection watchdog."""
        if self._watchdog_running:
            _LOG.debug("[%s] Stopping connection watchdog", self.log_id)
            self._watchdog_running = False
            if self._watchdog_task and not self._watchdog_task.done():
                self._watchdog_task.cancel()
                try:
                    await self._watchdog_task
                except asyncio.CancelledError:
                    pass
            self._watchdog_task = None

    async def _watchdog_loop(self) -> None:
        """Watchdog loop that monitors connection and reconnects if needed."""
        _LOG.info(
            "[%s] Connection watchdog started (check interval: %ds)",
            self.log_id,
            self._watchdog_interval,
        )

        while self._watchdog_running:
            try:
                await asyncio.sleep(self._watchdog_interval)

                # Check if we should be connected but aren't
                if not self._zwave_client.connected:
                    _LOG.warning(
                        "[%s] Connection lost, attempting to reconnect...", self.log_id
                    )
                    self._is_connected = False
                    self._state = PowerState.OFF
                    self.events.emit(EVENTS.DISCONNECTED, self.device_config.identifier)

                    # Try to reconnect
                    reconnect_success = await self._reconnect()

                    if reconnect_success:
                        _LOG.info("[%s] Reconnection successful", self.log_id)
                        self.events.emit(
                            EVENTS.CONNECTED, self.device_config.identifier
                        )
                    else:
                        _LOG.error(
                            "[%s] Reconnection failed, will retry in %ds",
                            self.log_id,
                            self._watchdog_interval,
                        )
                else:
                    _LOG.debug("[%s] Connection check: OK", self.log_id)

            except asyncio.CancelledError:
                _LOG.debug("[%s] Watchdog loop cancelled", self.log_id)
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOG.error("[%s] Error in watchdog loop: %s", self.log_id, err)
                await asyncio.sleep(self._reconnect_delay)

    async def _reconnect(self) -> bool:
        """Attempt to reconnect to the Z-Wave controller."""
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                _LOG.info(
                    "[%s] Reconnection attempt %d/%d",
                    self.log_id,
                    attempt,
                    max_attempts,
                )

                # Disconnect first to clean up
                try:
                    await self._zwave_client.disconnect()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

                # Wait before reconnecting
                await asyncio.sleep(self._reconnect_delay)

                # Try to connect
                success = await self._zwave_client.connect()

                if success:
                    self._is_connected = True
                    self._state = PowerState.ON
                    _LOG.info("[%s] Reconnected to Z-Wave controller", self.log_id)

                    # Re-setup event handlers
                    self._setup_event_handlers()

                    return True
                else:
                    _LOG.warning(
                        "[%s] Reconnection attempt %d failed", self.log_id, attempt
                    )

            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOG.error(
                    "[%s] Reconnection attempt %d error: %s", self.log_id, attempt, err
                )

            if attempt < max_attempts:
                await asyncio.sleep(self._reconnect_delay)

        return False

    def _on_value_updated(self, event_info: dict) -> None:
        """Handle Z-Wave value updated events."""
        try:
            node_id = event_info.get("node_id")
            
            if node_id is None:
                _LOG.warning("⚠️  [%s] Received value update with no node_id: %s", self.log_id, event_info)
                return
            
            # Validate node_id is numeric
            if not isinstance(node_id, int):
                _LOG.error("❌ [%s] node_id is not an integer: %s (type: %s)", 
                          self.log_id, node_id, type(node_id).__name__)
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
                _LOG.debug("[%s] Node %d is not a known light or cover, ignoring update", self.log_id, node_id)
                
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("❌ [%s] Error handling value update: %s", self.log_id, ex, exc_info=True)

    def _on_node_status_changed(self, event_info: dict) -> None:
        """Handle Z-Wave node status changed events."""
        _LOG.debug("[%s] Node status changed: %s", self.log_id, event_info)

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
                    _LOG.warning("⚠️  [%s] new_value is None for light node_id=%s, skipping update", self.log_id, node_id)
                    return
                
                if isinstance(new_value, dict):
                    _LOG.error("❌ [%s] new_value is a dict for light node_id=%s, expected int/float. Data: %s", 
                              self.log_id, node_id, new_value)
                    return
                
                if not isinstance(new_value, (int, float)):
                    _LOG.error("❌ [%s] new_value has invalid type %s for light node_id=%s, expected int/float. Value: %s", 
                              self.log_id, type(new_value).__name__, node_id, new_value)
                    return
                
                # Validate range (0-100 for Z-Wave)
                if not (0 <= new_value <= 100):
                    _LOG.warning("⚠️  [%s] Brightness value %s out of range [0-100] for light node_id=%s, clamping", 
                               self.log_id, new_value, node_id)
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
            update["state"] = "ON" if light.current_state > 0 else "OFF"
            update["brightness"] = light.brightness

            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self.device_config.identifier,
                    str(light.node_id),
                    EntityTypes.LIGHT,
                ),
                update,
            )

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Light update: protocol error", self.log_id)

    async def get_lights(self) -> list[Any]:
        """Return the list of light entities from Z-Wave network."""
        if not self._zwave_client or not self._zwave_client.connected:
            await self.connect()

        devices = self._zwave_client.get_devices()
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
                await self._zwave_client.turn_off(node_id)
            elif brightness == 99:
                await self._zwave_client.turn_on(node_id)
            else:
                await self._zwave_client.set_dimmer_level(node_id, brightness)

            update["state"] = "ON" if brightness > 0 else "OFF"
            update["brightness"] = 100 if brightness == 99 else brightness

            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self._config.identifier,
                    light_id,
                    EntityTypes.LIGHT,
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
                    await self._zwave_client.turn_off(node_id)
                else:
                    await self._zwave_client.turn_on(node_id)
                self.events.emit(
                    EVENTS.UPDATE,
                    create_entity_id(
                        self._config.identifier,
                        light_id,
                        EntityTypes.LIGHT,
                    ),
                    {
                        "state": "OFF" if is_on else "ON",
                        "brightness": 0 if is_on else 255,
                    },
                )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error toggling light %s: %s", self.log_id, light_id, err)

    async def get_covers(self) -> list[Any]:
        """Return the list of cover entities from Z-Wave network."""
        if not self._zwave_client or not self._zwave_client.connected:
            await self.connect()

        devices = self._zwave_client.get_devices()
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
            await self._zwave_client.set_dimmer_level(node_id, position)

            # Determine state based on position
            if position <= 5:
                state = "CLOSED"
            elif position >= 95:
                state = "OPEN"
            else:
                state = "OPENING" if position > 50 else "CLOSING"

            update["state"] = state
            update["position"] = position

            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self._config.identifier,
                    cover_id,
                    EntityTypes.COVER,
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
            cover = next(
                (entity for entity in self._covers if entity.node_id == node_id), None
            )
            if cover:
                # Send the current position to stop movement
                await self._zwave_client.set_dimmer_level(node_id, cover.position)
                _LOG.debug(
                    "[%s] Stopped cover %s at position %s",
                    self.log_id,
                    cover_id,
                    cover.position,
                )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error stopping cover %s: %s", self.log_id, cover_id, err)

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
                    _LOG.warning("⚠️  [%s] new_value is None for cover node_id=%s, skipping update", self.log_id, node_id)
                    return
                
                if isinstance(new_value, dict):
                    _LOG.error("❌ [%s] new_value is a dict for cover node_id=%s, expected int/float. Data: %s", 
                              self.log_id, node_id, new_value)
                    return
                
                if not isinstance(new_value, (int, float)):
                    _LOG.error("❌ [%s] new_value has invalid type %s for cover node_id=%s, expected int/float. Value: %s", 
                              self.log_id, type(new_value).__name__, node_id, new_value)
                    return
                
                # Validate range (0-100 for position)
                if not (0 <= new_value <= 100):
                    _LOG.warning("⚠️  [%s] Cover position value %s out of range [0-100] for node_id=%s, clamping", 
                               self.log_id, new_value, node_id)
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

            # Determine state based on position
            position = cover.position
            if position <= 5:
                state = "CLOSED"
            elif position >= 95:
                state = "OPEN"
            else:
                state = "OPENING" if position > 50 else "CLOSING"

            # Prepare update event
            update["state"] = state
            update["position"] = position

            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self.device_config.identifier,
                    str(cover.node_id),
                    EntityTypes.COVER,
                ),
                update,
            )

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Cover update: protocol error", self.log_id)
