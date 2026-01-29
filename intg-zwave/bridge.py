"""
This module implements the Z-Wave communication of the Remote Two/3 integration driver.

"""

import logging
from asyncio import AbstractEventLoop
from typing import Any

from const import ZWaveCoverInfo, ZWaveConfig, ZWaveLightInfo
from ucapi import EntityTypes
from ucapi.cover import States as CoverStates
from ucapi.light import States as LightStates
from ucapi_framework import (
    ExternalClientDevice,
    create_entity_id,
    CoverAttributes,
    LightAttributes,
    BaseIntegrationDriver,
)
from zwave_client import ZWaveClient

_LOG = logging.getLogger(__name__)


class SmartHub(ExternalClientDevice):
    """Representing a Z-Wave Controller."""

    def __init__(
        self,
        config: ZWaveConfig,
        loop: AbstractEventLoop | None = None,
        config_manager=None,
        driver: BaseIntegrationDriver | None = None,
        watchdog_interval: int = 30,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 3,
    ) -> None:
        """Create instance."""
        super().__init__(
            device_config=config,
            loop=loop,
            config_manager=config_manager,
            driver=driver,
            watchdog_interval=watchdog_interval,
            reconnect_delay=reconnect_delay,
            max_reconnect_attempts=max_reconnect_attempts,
        )
        self._lights: list[ZWaveLightInfo] = []
        self._covers: list[ZWaveCoverInfo] = []
        # Attribute storage for entities
        self._light_attributes: dict[str, LightAttributes] = {}
        self._cover_attributes: dict[str, CoverAttributes] = {}

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
    def device_config(self) -> ZWaveConfig:
        """Return the device configuration."""
        return self._device_config

    @property
    def state(self) -> str:
        """Return the device state."""
        return "ON" if self.is_connected else "OFF"

    @property
    def lights(self) -> list[ZWaveLightInfo]:
        """Return the list of light entities."""
        return self._lights

    @property
    def covers(self) -> list[ZWaveCoverInfo]:
        """Return the list of cover entities."""
        return self._covers

    @property
    def light_attributes(self) -> dict[str, LightAttributes]:
        """Return the light attributes dictionary."""
        return self._light_attributes

    @property
    def cover_attributes(self) -> dict[str, CoverAttributes]:
        """Return the cover attributes dictionary."""
        return self._cover_attributes

    def get_device_attributes(
        self, entity_id: str
    ) -> dict[str, Any] | LightAttributes | CoverAttributes:
        """
        Provide entity-specific attributes for the given entity.

        :param entity_id: Entity identifier to get attributes for
        :return: Dictionary of entity attributes or dataclass instance
        """
        # Check if it's a light entity
        if entity_id in self.light_attributes:
            return self.light_attributes[entity_id]

        # Check if it's a cover entity
        if entity_id in self.cover_attributes:
            return self.cover_attributes[entity_id]

        return {}

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

        # Populate lights and covers from Z-Wave network
        await self.get_lights()
        await self.get_covers()

        # Initialize attributes for each entity
        for light_info in self._lights:
            entity_id = create_entity_id(
                EntityTypes.LIGHT,
                self._device_config.identifier,
                str(light_info.node_id),
            )
            brightness = int(light_info.brightness)
            self._light_attributes[entity_id] = LightAttributes(
                STATE=LightStates.ON if brightness > 0 else LightStates.OFF,
                BRIGHTNESS=brightness,
            )

        for cover_info in self._covers:
            entity_id = create_entity_id(
                EntityTypes.COVER,
                self._device_config.identifier,
                str(cover_info.node_id),
            )
            # Convert Z-Wave position (0-99) to UI position (0-100)
            ui_position = 100 if cover_info.position >= 99 else int(cover_info.position)

            self._cover_attributes[entity_id] = CoverAttributes(
                STATE=CoverStates.OPEN
                if cover_info.position > 50
                else CoverStates.CLOSED,
                POSITION=ui_position,
            )

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
                "⚡ BRIDGE [%s]: Value updated - node %d, event_info: %s",
                self.log_id,
                node_id,
                event_info,
            )

            # Check if it's a light or cover and update accordingly
            is_light = any(light.node_id == node_id for light in self._lights)
            is_cover = any(cover.node_id == node_id for cover in self._covers)

            # For covers, handle targetValue and duration properties specially
            if is_cover:
                property_name = event_info.get("property", "")
                if property_name == "duration":
                    _LOG.debug(
                        "[%s] Ignoring cover property 'duration' for node %d",
                        self.log_id,
                        node_id,
                    )
                    return
                elif property_name == "targetValue":
                    # targetValue indicates the cover has reached its destination
                    # Update state to OPEN (or CLOSED if position is 0-1)
                    _LOG.debug(
                        "[%s] Cover targetValue reached for node %d, setting to stationary state",
                        self.log_id,
                        node_id,
                    )
                    self._set_cover_stationary(node_id)
                    return

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

    def _update_light(self, node_id: int, event_info: dict | None = None) -> None:
        """Update light state in cache and store in attributes."""
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
                        "[%s] Skipping non-brightness value for light node_id=%s (dict): %s",
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

            # Store attributes in dataclass
            entity_id = create_entity_id(
                EntityTypes.LIGHT,
                self._device_config.identifier,
                str(light.node_id),
            )

            # Get old attributes to compare
            old_attributes = self._light_attributes.get(entity_id)

            # Create new attributes based on current state
            brightness = 0 if light.current_state == 0 else int(light.brightness)
            new_attributes = LightAttributes(
                STATE=LightStates.ON if brightness > 0 else LightStates.OFF,
                BRIGHTNESS=brightness,
            )
            self._light_attributes[entity_id] = new_attributes

            # Emit update event if attributes changed
            if event_info and old_attributes != new_attributes:
                if self._driver:
                    entity = self._driver.get_entity_by_id(entity_id)
                    if entity:
                        entity.update(new_attributes)

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Light update: protocol error", self.log_id)

    async def get_lights(self) -> list[Any]:
        """Return the list of light entities from Z-Wave network."""
        if not self._client or not self._client.connected:
            return []

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
                # Get current value from Z-Wave (0-100)
                zwave_value = device_info.get("current_value", 0)
                # Convert Z-Wave brightness (0-100) to ucapi brightness (0-255)
                brightness = 0 if zwave_value == 0 else int(zwave_value * 255 / 100)

                light_list.append(
                    ZWaveLightInfo(
                        device_id=str(node_id),
                        node_id=node_id,
                        current_state=brightness,
                        brightness=brightness,
                        type=device_type,
                        name=device_info.get("name", f"Node {node_id}"),
                        model=device_info.get("device_type", "Unknown"),
                    )
                )

        # Update internal lights list
        self._lights = light_list

        return light_list

    async def control_light(self, light_id: int, brightness: int) -> None:
        """Control a light with a specific brightness."""
        try:
            node_id = int(light_id)
            if brightness == 0:
                await self._client.turn_off(node_id)
            elif brightness == 99:
                await self._client.turn_on(node_id)
            else:
                await self._client.set_dimmer_level(node_id, brightness)

            entity_id = create_entity_id(
                EntityTypes.LIGHT,
                self._device_config.identifier,
                str(light_id),
            )

            self._light_attributes[entity_id] = LightAttributes(
                STATE=LightStates.ON if brightness > 0 else LightStates.OFF,
                BRIGHTNESS=100 if brightness == 99 else int(brightness * 255 / 100),
            )

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error turning on light %s: %s", self.log_id, light_id, err)

    async def toggle_light(self, light_id: int) -> None:
        """Toggle a light."""
        try:
            # Get current state from lights list
            light = next(
                (
                    light_entity
                    for light_entity in self._lights
                    if light_entity.node_id == light_id
                ),
                None,
            )
            if light:
                is_on = light.current_state > 0
                node_id = light.node_id
                if is_on:
                    await self._client.turn_off(node_id)
                else:
                    await self._client.turn_on(node_id)

                entity_id = create_entity_id(
                    EntityTypes.LIGHT,
                    self._device_config.identifier,
                    str(light_id),
                )

                self._light_attributes[entity_id] = LightAttributes(
                    STATE=LightStates.OFF if is_on else LightStates.ON,
                    BRIGHTNESS=0 if is_on else 255,
                )
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Error toggling light %s: %s", self.log_id, light_id, err)

    # ─────────────────────────────────────────────────────────────────
    # Cover Operations
    # ─────────────────────────────────────────────────────────────────

    def _set_cover_stationary(self, node_id: int) -> None:
        """Set cover to stationary state (OPEN or CLOSED based on current position)."""
        try:
            cover = next(
                (entity for entity in self._covers if entity.node_id == node_id), None
            )
            if not cover:
                return

            entity_id = create_entity_id(
                EntityTypes.COVER,
                self._device_config.identifier,
                str(node_id),
            )

            # Get current position
            ui_position = 100 if cover.position >= 99 else int(cover.position)

            # Set state based on position: CLOSED if 0-1%, otherwise OPEN
            state = CoverStates.CLOSED if ui_position <= 1 else CoverStates.OPEN

            new_attributes = CoverAttributes(
                STATE=state,
                POSITION=ui_position,
            )
            self._cover_attributes[entity_id] = new_attributes

            # Send update with force=True
            if self._driver:
                entity = self._driver.get_entity_by_id(entity_id)
                if entity:
                    entity.update(new_attributes, force=True)

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Error setting cover stationary state", self.log_id)

    def _update_cover(self, node_id: int, event_info: dict | None = None) -> None:
        """Update cover state in cache and store in attributes."""
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
                    _LOG.debug(
                        "[%s] Skipping non-position value for cover node_id=%s (dict): %s",
                        self.log_id,
                        node_id,
                        new_value,
                    )
                    return

                # Handle string values (like "unknown") from Z-Wave
                if isinstance(new_value, str):
                    _LOG.debug(
                        "[%s] Received string value '%s' for cover node_id=%s, skipping update",
                        self.log_id,
                        new_value,
                        node_id,
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

                # Log the position change with additional context
                old_position = cover.position
                prev_value = event_info.get("prev_value")
                _LOG.info(
                    "📊 [%s] COVER EVENT: node_id=%s | old_cache=%s | new_value=%s | prev_value=%s | DIRECTION: %s",
                    self.log_id,
                    node_id,
                    old_position,
                    new_value,
                    prev_value,
                    "UP"
                    if new_value > old_position
                    else ("DOWN" if new_value < old_position else "STABLE"),
                )

                # Update cover state
                cover.position = new_value
                cover.current_state = cover.position

                _LOG.debug(
                    "[%s] Updated cover cache: node_id=%s, position=%s",
                    self.log_id,
                    node_id,
                    cover.position,
                )

            # Store attributes in dataclass
            entity_id = create_entity_id(
                EntityTypes.COVER,
                self._device_config.identifier,
                str(cover.node_id),
            )

            # Get old attributes to compare
            old_attributes = self._cover_attributes.get(entity_id)

            # Convert Z-Wave position (0-99) to UI position (0-100)
            # Z-Wave often uses 99 as max to avoid "full on" issues
            ui_position = 100 if cover.position >= 99 else int(cover.position)

            # Determine state based on position and movement
            # Logic:
            # - 0-1% = CLOSED
            # - 2-99% moving up = OPENING
            # - 2-99% moving down = CLOSING
            # - 2-99% stationary = OPEN
            # - 100% = OPEN

            old_ui_position = (
                old_attributes.POSITION
                if old_attributes and old_attributes.POSITION is not None
                else ui_position
            )

            if ui_position <= 1:
                state = CoverStates.CLOSED
            elif old_ui_position < ui_position:
                # Position increased = opening
                state = CoverStates.OPENING
            elif old_ui_position > ui_position:
                # Position decreased = closing
                state = CoverStates.CLOSING
            else:
                # Position unchanged = stationary, use OPEN for any partial position
                state = CoverStates.OPEN

            new_attributes = CoverAttributes(
                STATE=state,
                POSITION=ui_position,
            )
            self._cover_attributes[entity_id] = new_attributes

            # Always update the entity with force=True to ensure state changes are sent
            if event_info and self._driver:
                entity = self._driver.get_entity_by_id(entity_id)
                if entity:
                    entity.update(new_attributes, force=True)

        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Cover update: protocol error", self.log_id)

    async def get_covers(self) -> list[Any]:
        """Return the list of cover entities from Z-Wave network."""
        if not self._client or not self._client.connected:
            return []

        _LOG.debug("[%s] ⏱️  Fetching devices from Z-Wave client...", self.log_id)
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

    async def control_cover(self, cover_id: int, position: int) -> None:
        """Control a cover to a specific position (0-100)."""
        try:
            node_id = int(cover_id)

            # Get current position to determine direction
            current_cover = next(
                (cover for cover in self._covers if cover.node_id == node_id), None
            )
            current_position = current_cover.position if current_cover else 50

            # Position: 0 = closed, 100 = open
            # Convert 100% to 99% for Z-Wave (many devices use 99 as max)
            zwave_position = 99 if position >= 100 else position

            await self._client.set_dimmer_level(node_id, zwave_position)

            # Determine initial state based on direction of movement
            if position <= 1:
                state = CoverStates.CLOSED
            elif position > current_position:
                state = CoverStates.OPENING
            elif position < current_position:
                state = CoverStates.CLOSING
            else:
                # No movement
                state = CoverStates.OPEN

            entity_id = create_entity_id(
                EntityTypes.COVER,
                self._device_config.identifier,
                str(cover_id),
            )

            self._cover_attributes[entity_id] = CoverAttributes(
                STATE=state,
                POSITION=position,
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
