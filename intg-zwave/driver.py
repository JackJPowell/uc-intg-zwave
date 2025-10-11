#!/usr/bin/env python3
"""
This module implements a Unfolded Circle integration driver for Z-Wave devices.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import sys
from typing import Any
import config
import setup
import ucapi
import ucapi.api as uc
from ucapi import EntityTypes
from light import ZWaveLight
from cover import ZWaveCover
from config import (
    ZWaveConfig,
    device_from_entity_id,
    entity_from_entity_id,
    create_entity_id,
    type_from_entity_id,
)
import bridge

_LOG = logging.getLogger("driver")  # avoid having __main__ in log messages
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# Global variables
api = uc.IntegrationAPI(_LOOP)
_configured_devices: dict[str, bridge.SmartHub] = {}


@api.listens_to(ucapi.Events.CONNECT)
async def on_r2_connect_cmd() -> None:
    """Connect all configured devices when the Remote Two sends the connect command."""
    _LOG.debug("Client connect command: connecting device(s)")
    await api.set_device_state(
        ucapi.DeviceStates.CONNECTED
    )  # just to make sure the device state is set
    for device in _configured_devices.values():
        await device.connect()


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_r2_disconnect_cmd():
    """Disconnect all configured devices when the Remote Two/3 sends the disconnect command."""
    _LOG.debug("Client disconnect command: disconnecting Z-Wave controller(s)")
    for device in _configured_devices.values():
        await device.disconnect()


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_r2_enter_standby() -> None:
    """
    Enter standby notification from Remote Two/3.

    Disconnect every Z-Wave controller instances.
    """
    _LOG.debug("Enter standby event: disconnecting Z-Wave controller(s)")
    for device in _configured_devices.values():
        await device.disconnect()


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_r2_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all Z-Wave instances.
    """
    _LOG.debug("Exit standby event: connecting device(s)")
    for device in _configured_devices.values():
        await device.connect()


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """
    Subscribe to given entities.

    :param entity_ids: entity identifiers.
    """
    _LOG.debug("Subscribe entities event: %s", entity_ids)

    if entity_ids is not None and len(entity_ids) > 0:
        device_id = device_from_entity_id(entity_ids[0])
        if device_id not in _configured_devices:
            device_config = config.devices.get(device_id)
            if device_config:
                # Add and connect to the device, which will also register entities
                await _add_configured_device(device_config, connect=True)
            else:
                _LOG.error(
                    "Failed to subscribe entity %s: no instance found", device_id
                )
                return

        device = _configured_devices.get(device_id)
        if device and not device.is_connected:
            attempt = 0
            while attempt := attempt + 1 < 4:
                _LOG.debug(
                    "Device %s not connected, attempting to connect (%d/3)",
                    device_id,
                    attempt,
                )
                if await device.connect():
                    # After successful connection, register entities from the hub
                    await _register_available_entities_from_hub(device)
                    break
                else:
                    await device.disconnect()
                    await asyncio.sleep(0.5)

    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        device = _configured_devices[device_id]
        match type_from_entity_id(entity_id):
            case EntityTypes.COVER.value:
                entity = next(
                    (
                        cover
                        for cover in device.covers
                        if cover.node_id == entity_from_entity_id(entity_id)
                    ),
                    None,
                )

                if entity is not None:
                    update = {}
                    update["state"] = "OPEN" if entity.position > 0 else "CLOSED"
                    update["position"] = int(entity.position)
                    api.configured_entities.update_attributes(entity_id, update)
            case EntityTypes.LIGHT.value:
                entity = next(
                    (
                        light
                        for light in device.lights
                        if light.device_id == entity_from_entity_id(entity_id)
                    ),
                    None,
                )

                if entity is not None:
                    update = {}
                    update["state"] = "ON" if entity.current_state > 0 else "OFF"
                    update["brightness"] = int(entity.current_state * 255 / 100)
                    api.configured_entities.update_attributes(entity_id, update)
        continue


@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, we disconnect the objects and remove listeners for events."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        if device_id is None:
            continue
        _configured_devices[device_id].events.remove_all_listeners()


async def on_device_connected(device_id: str):
    """Handle device connection."""
    _LOG.debug("Z-Wave controller connected: %s", device_id)
    if str(device_id) not in _configured_devices:
        _LOG.warning("Z-Wave controller %s is not configured", device_id)
        return

    await api.set_device_state(ucapi.DeviceStates.CONNECTED)


async def on_device_disconnected(device_id: str):
    """Handle device disconnection."""
    _LOG.debug("Z-Wave controller disconnected: %s", device_id)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        # if configured_entity.entity_type == ucapi.EntityTypes.LIGHT:
        #     api.configured_entities.update_attributes(
        #         entity_id,
        #         {ucapi.light.Attributes.STATE: ucapi.light.States.UNAVAILABLE},
        #     )
        # elif configured_entity.entity_type == ucapi.EntityTypes.COVER:
        #     api.configured_entities.update_attributes(
        #         entity_id,
        #         {ucapi.cover.Attributes.STATE: ucapi.cover.States.UNAVAILABLE},
        #     )


async def on_device_connection_error(device_id: str, message):
    """Set entities of Z-Wave controller to state UNAVAILABLE if device connection error occurred."""
    _LOG.error(message)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.LIGHT:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.light.Attributes.STATE: ucapi.light.States.UNAVAILABLE},
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.COVER:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.cover.Attributes.STATE: ucapi.cover.States.UNAVAILABLE},
            )

    await api.set_device_state(ucapi.DeviceStates.ERROR)


# pylint: disable=too-many-branches,too-many-statements
async def on_device_update(entity_id: str, update: dict[str, Any] | None) -> None:
    """
    Update attributes of configured media-player entity if Device properties changed.

    :param entity_id: Device media-player entity identifier
    :param update: dictionary containing the updated properties or None
    """
    attributes = {}
    configured_entity = api.available_entities.get(entity_id)
    if configured_entity is None:
        return

    if isinstance(configured_entity, ZWaveLight):
        if "state" in update:
            attributes[ucapi.light.Attributes.STATE] = update["state"]

        if "brightness" in update:
            attributes[ucapi.light.Attributes.BRIGHTNESS] = update["brightness"]

    elif isinstance(configured_entity, ZWaveCover):
        if "state" in update:
            attributes[ucapi.cover.Attributes.STATE] = update["state"]

        if "position" in update:
            attributes[ucapi.cover.Attributes.POSITION] = update["position"]

    if attributes:
        if api.configured_entities.contains(entity_id):
            api.configured_entities.update_attributes(entity_id, attributes)
        else:
            api.available_entities.update_attributes(entity_id, attributes)


async def _add_configured_device(
    device_config: ZWaveConfig, connect: bool = True
) -> None:
    """Add and optionally connect to a Z-Wave controller, then register its entities.

    :param device_config: The Z-Wave controller configuration
    :param connect: Whether to connect immediately (default True)
    """
    # the device should not yet be configured, but better be safe
    if device_config.identifier in _configured_devices:
        _LOG.debug(
            "DISCONNECTING: Existing configured device updated, update the running device %s",
            device_config,
        )
        device = _configured_devices[str(device_config.identifier)]
        await device.disconnect()

    _LOG.debug(
        "Adding new device: %s (%s)",
        device_config.identifier,
        device_config.address,
    )
    device = bridge.SmartHub(device_config, loop=_LOOP)
    device.events.on(bridge.EVENTS.CONNECTED, on_device_connected)
    device.events.on(bridge.EVENTS.DISCONNECTED, on_device_disconnected)
    device.events.on(bridge.EVENTS.ERROR, on_device_connection_error)
    device.events.on(bridge.EVENTS.UPDATE, on_device_update)

    _configured_devices[str(device.identifier)] = device

    if connect:
        # Connect to the Z-Wave controller first
        _LOG.debug("Connecting to Z-Wave controller: %s", device_config.identifier)
        connected = await device.connect()

        if connected:
            _LOG.info(
                "Successfully connected to Z-Wave controller: %s",
                device_config.identifier,
            )

            # Now that we're connected, register entities from the hub
            await _register_available_entities_from_hub(device)
        else:
            _LOG.error(
                "Failed to connect to Z-Wave controller: %s", device_config.identifier
            )


async def _register_available_entities_from_hub(device: bridge.SmartHub) -> bool:
    """
    Register entities by querying the Z-Wave hub for its devices.

    This is called after the hub is connected and retrieves the actual
    devices from the Z-Wave network rather than from stored config.

    :param device: The connected SmartHub instance
    :return: True if entities were registered successfully
    """
    _LOG.info("Registering available entities from Z-Wave hub: %s", device.identifier)

    try:
        # Get lights from the hub (this queries the Z-Wave network)
        lights = await device.get_lights()
        _LOG.debug("Found %d lights on Z-Wave network", len(lights))

        entities = []

        # Create light entities from what the hub reports
        for light_info in lights:
            _LOG.debug(
                "Registering light: %s (node %d)", light_info.name, light_info.node_id
            )
            light_entity = ZWaveLight(
                device.device_config, light_info, get_configured_device
            )
            entities.append(light_entity)

        # Get covers from the hub (this queries the Z-Wave network)
        covers = await device.get_covers()
        _LOG.debug("Found %d covers on Z-Wave network", len(covers))

        # Create cover entities from what the hub reports
        for cover_info in covers:
            _LOG.debug(
                "Registering cover: %s (node %d)", cover_info.name, cover_info.node_id
            )
            cover_entity = ZWaveCover(
                device.device_config, cover_info, get_configured_device
            )
            entities.append(cover_entity)

        # Register all entities with the API
        for entity in entities:
            if api.available_entities.contains(entity.id):
                _LOG.debug("Removing existing entity: %s", entity.id)
                api.available_entities.remove(entity.id)
            _LOG.debug("Adding entity: %s", entity.id)
            api.available_entities.add(entity)

        _LOG.info("Successfully registered %d entities from Z-Wave hub", len(entities))
        return True

    except Exception as ex:  # pylint: disable=broad-exception-caught
        _LOG.error("Error registering entities from hub: %s", ex)
        return False


def _entities_from_device_id(device_id: str) -> list[str]:
    """
    Return all associated entity identifiers of the given device.

    :param device_id: the device identifier
    :return: list of entity identifiers
    """
    entities = []
    device = _configured_devices.get(device_id)
    if device:
        # Get entities from the actual hub, not from stored config
        entities.extend(
            create_entity_id(device.identifier, str(light.node_id), EntityTypes.LIGHT)
            for light in device.lights
        )
        entities.extend(
            create_entity_id(device.identifier, str(cover.node_id), EntityTypes.COVER)
            for cover in device.covers
        )
    return entities


def on_device_added(device: ZWaveConfig) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New Z-Wave controller added: %s", device)
    # Schedule the async device addition
    _LOOP.create_task(_add_configured_device(device, connect=True))


def on_device_removed(device: ZWaveConfig | None) -> None:
    """Handle a removed device in the configuration."""
    if device is None:
        _LOG.debug(
            "Configuration cleared, disconnecting & removing all configured device instances"
        )
        for device in _configured_devices.values():
            device.events.remove_all_listeners()
        _configured_devices.clear()
        api.configured_entities.clear()
        api.available_entities.clear()
    else:
        if device.identifier in _configured_devices:
            _LOG.debug("Disconnecting from removed device %s", device.identifier)
            device = _configured_devices.pop(device.identifier)
            device.events.remove_all_listeners()
            entity_id = device.identifier
            api.configured_entities.remove(entity_id)
            api.available_entities.remove(entity_id)


def get_configured_device(device_id: str) -> bridge.SmartHub | None:
    """Return the configured device instance for the given device identifier."""
    return _configured_devices.get(str(device_id))


async def main():
    """Start the Remote Two/3 integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("bridge").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)

    config.devices = config.Devices(
        api.config_dir_path, on_device_added, on_device_removed
    )

    # Connect to all configured Z-Wave controllers and register their entities
    for device_config in config.devices.all():
        _LOG.info("Initializing Z-Wave controller: %s", device_config.identifier)
        await _add_configured_device(device_config, connect=True)

    await api.init("driver.json", setup.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
