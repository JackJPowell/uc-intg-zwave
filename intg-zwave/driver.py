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
            device = config.devices.get(device_id)
            if device:
                _add_configured_device(device)
            else:
                _LOG.error(
                    "Failed to subscribe entity %s: no instance found", device_id
                )
                return
        device = _configured_devices[device_id]
        if not device.is_connected:
            attempt = 0
            while attempt := attempt + 1 < 4:
                _LOG.debug(
                    "Device %s not connected, attempting to connect (%d/3)",
                    device_id,
                    attempt,
                )
                if not await device.connect():
                    await device.disconnect()
                    await asyncio.sleep(0.5)
                else:
                    break

    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        device = _configured_devices[device_id]
        match type_from_entity_id(entity_id):
            case EntityTypes.BUTTON.value:
                entity = next(
                    (
                        scene
                        for scene in device.scenes
                        if scene.scene_id == entity_from_entity_id(entity_id)
                    ),
                    None,
                )

                if entity is not None:
                    update = {}
                    update["state"] = "AVAILABLE"
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
        elif configured_entity.entity_type == ucapi.EntityTypes.BUTTON:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.button.Attributes.STATE: ucapi.button.States.UNAVAILABLE},
            )


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
        elif configured_entity.entity_type == ucapi.EntityTypes.BUTTON:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.button.Attributes.STATE: ucapi.button.States.UNAVAILABLE},
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

    elif configured_entity.entity_type == ucapi.EntityTypes.BUTTON:
        if "state" in update:
            attributes[ucapi.button.Attributes.STATE] = "AVAILABLE"

    # elif isinstance(configured_entity, ZwaveCover):
    #     target_entity = api.available_entities.get(identifier)

    if attributes:
        if api.configured_entities.contains(entity_id):
            api.configured_entities.update_attributes(entity_id, attributes)
        else:
            api.available_entities.update_attributes(entity_id, attributes)


def _add_configured_device(device_config: ZWaveConfig, connect: bool = False) -> None:
    # the device should not yet be configured, but better be safe
    if device_config.identifier in _configured_devices:
        _LOG.debug(
            "DISCONNECTING: Existing configured device updated, update the running device %s",
            device_config,
        )
        device = _configured_devices[str(device_config.identifier)]
        _LOOP.create_task(device.disconnect())
    else:
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

    async def start_connection():
        await device.connect()

    if connect:
        _LOOP.create_task(start_connection())

    _register_available_entities(device_config)


def _register_available_entities(device_config: ZWaveConfig) -> bool:
    """
    Add a new device to the available entities.

    :param identifier: identifier
    :param name: Friendly name
    :return: True if added, False if the device was already in storage.
    """
    _LOG.info("_register_available_entities for %s", device_config.identifier)
    entities = []

    for entity in device_config.lights:
        entities.append(ZWaveLight(device_config, entity, get_configured_device))

    for entity in entities:
        if api.available_entities.contains(entity):
            api.available_entities.remove(entity)
        api.available_entities.add(entity)
    return True


def _entities_from_device_id(device_id: str) -> list[str]:
    """
    Return all associated entity identifiers of the given device.

    :param device_id: the device identifier
    :return: list of entity identifiers
    """
    # get from config
    entities = []
    device = config.devices.get(device_id)
    if device:
        entities.extend(
            create_entity_id(device.identifier, scene.scene_id, EntityTypes.BUTTON)
            for scene in device.scenes
        )
        entities.extend(
            create_entity_id(device.identifier, light.device_id, EntityTypes.LIGHT)
            for light in device.lights
        )
    return entities


def on_device_added(device: ZWaveConfig) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New Z-Wave controller added: %s", device)
    _add_configured_device(device)


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

    for device_config in config.devices.all():
        _register_available_entities(device_config)

    await api.init("driver.json", setup.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
