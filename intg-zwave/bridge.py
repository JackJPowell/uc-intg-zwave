"""
This module implements the Z-Wave communication of the Remote Two/3 integration driver.

"""

import asyncio
import logging
from dataclasses import dataclass
from asyncio import AbstractEventLoop
from enum import StrEnum, IntEnum
from typing import Any, ParamSpec, TypeVar

from zwave_client import ZWaveClient
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr
from ucapi import EntityTypes
from config import ZWaveConfig, create_entity_id
from const import ZWaveLightInfo

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


@dataclass
class ZWaveCoverInfo:
    device_id: str
    node_id: int
    current_state: int
    type: str
    name: str


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
    def lights(self) -> list[Any]:
        """Return the list of light entities."""
        return self._lights

    @property
    def covers(self) -> list[Any]:
        """Return the list of cover entities."""
        return self._covers

    @property
    def is_connected(self) -> bool:
        """Return if the device is connected."""
        return self._is_connected

    async def connect(self) -> bool:
        """Establish connection to the Z-Wave controller."""
        if self._zwave_client.connected:
            return True

        _LOG.debug("[%s] Connecting to Z-Wave controller", self.log_id)
        self.events.emit(EVENTS.CONNECTING, self.device_config.identifier)

        try:
            success = await self._zwave_client.connect()
            if not success:
                return False

            self._is_connected = True
            self._state = PowerState.ON
            _LOG.info("[%s] Connected to Z-Wave controller", self.log_id)

            # Set up event handlers
            self._zwave_client.add_event_handler(
                "value_updated", self._on_value_updated
            )
            self._zwave_client.add_event_handler(
                "node_status_changed", self._on_node_status_changed
            )

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

        self._update_lights()
        return True

    async def disconnect(self) -> None:
        """Disconnect from the Z-Wave controller."""
        _LOG.debug("[%s] Disconnecting from Z-Wave controller", self.log_id)
        await self._zwave_client.disconnect()
        self._is_connected = False
        self._state = PowerState.OFF
        self.events.emit(EVENTS.DISCONNECTED, self.device_config.identifier)

    def _on_value_updated(self, event_info: dict) -> None:
        """Handle Z-Wave value updated events."""
        _LOG.debug("[%s] Value updated: %s", self.log_id, event_info)
        self._update_lights()

    def _on_node_status_changed(self, event_info: dict) -> None:
        """Handle Z-Wave node status changed events."""
        _LOG.debug("[%s] Node status changed: %s", self.log_id, event_info)

    def _update_lights(self) -> None:
        update = {}
        try:
            self._lights = self.get_lights()

            for entity in self._lights:
                update = {}
                update["state"] = "ON" if entity.current_state > 0 else "OFF"
                update["brightness"] = entity.brightness

                self.events.emit(
                    EVENTS.UPDATE,
                    create_entity_id(
                        self.device_config.identifier,
                        str(entity.node_id),
                        EntityTypes.LIGHT,
                    ),
                    update,
                )

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Light update: protocol error", self.log_id)

    def get_lights(self) -> list[Any]:
        """Return the list of light entities from Z-Wave network."""
        if not self._zwave_client or not self._zwave_client.connected:
            return []

        devices = self._zwave_client.get_devices()
        light_list = []

        for node_id, device_info in devices.items():
            # Check if device is a light/dimmer (this is a simplified check)
            device_type = device_info.get("device_type", "").lower()
            if (
                "switch" in device_type
                or "dimmer" in device_type
                or "multilevel" in device_type
            ):
                # Try to get current state
                current_state = 0
                brightness = 0
                # This would need to be enhanced based on actual Z-Wave device values

                light_list.append(
                    ZWaveLightInfo(
                        device_id=str(node_id),
                        node_id=node_id,
                        current_state=current_state,
                        brightness=brightness,
                        type=device_type,
                        name=device_info.get("name", f"Node {node_id}"),
                        model=device_info.get("device_type", "Unknown"),
                    )
                )
        return light_list

    async def turn_on_light(self, light_id: str, brightness: int = None) -> None:
        """Turn on a light with a specific brightness."""
        try:
            node_id = int(light_id)
            if brightness is not None:
                # Convert brightness from 0-255 to 0-100 for Z-Wave
                zwave_brightness = int(brightness * 100 / 255)
                await self._zwave_client.set_dimmer_level(node_id, zwave_brightness)
            else:
                await self._zwave_client.turn_on(node_id)

            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self._config.identifier,
                    light_id,
                    EntityTypes.LIGHT,
                ),
                {"state": "ON", "brightness": brightness if brightness else 255},
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error turning on light %s: %s", self.log_id, light_id, err)

    async def turn_off_light(self, light_id: str) -> None:
        """Turn off a light."""
        try:
            node_id = int(light_id)
            await self._zwave_client.turn_off(node_id)
            self.events.emit(
                EVENTS.UPDATE,
                create_entity_id(
                    self._config.identifier,
                    light_id,
                    EntityTypes.LIGHT,
                ),
                {"state": "OFF", "brightness": 0},
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error(
                "[%s] Error turning off light %s: %s", self.log_id, light_id, err
            )

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
