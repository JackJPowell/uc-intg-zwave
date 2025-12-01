#!/usr/bin/env python3
"""
This module implements a Unfolded Circle integration driver for Z-Wave devices.

:copyright: (c) 2025 by Jack Powell.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os

from bridge import SmartHub
from const import ZWaveDevice
from cover import ZWaveCover
from light import ZWaveLight
from setup import ZWaveSetupFlow
from ucapi import EntityTypes
from ucapi.cover import Attributes as CoverAttr
from ucapi.light import Attributes as LightAttr
from ucapi_framework import BaseDeviceManager, BaseIntegrationDriver, get_config_path

_LOG = logging.getLogger("driver")


class ZWaveIntegrationDriver(BaseIntegrationDriver[SmartHub, ZWaveDevice]):
    """ZWave Integration Driver"""

    async def refresh_entity_state(self, entity_id: str) -> None:
        """Refresh the state of a specific entity."""

        device_id = self.device_from_entity_id(entity_id)
        device = self._configured_devices[device_id]
        match self.entity_type_from_entity_id(entity_id):
            case EntityTypes.COVER.value:
                entity = next(
                    (
                        cover
                        for cover in device.covers
                        if cover.node_id == int(self.entity_from_entity_id(entity_id))
                    ),
                    None,
                )

                if entity is not None:
                    update = {}
                    update[CoverAttr.STATE] = (
                        "OPEN" if entity.position > 50 else "CLOSED"
                    )
                    update[CoverAttr.POSITION] = (
                        100 if entity.position == 99 else int(entity.position)
                    )
                    self.api.configured_entities.update_attributes(entity_id, update)
            case EntityTypes.LIGHT.value:
                entity = next(
                    (
                        light
                        for light in device.lights
                        if light.device_id == self.entity_from_entity_id(entity_id)
                    ),
                    None,
                )

                if entity is not None:
                    update = {}
                    update[LightAttr.STATE] = (
                        "ON" if entity.current_state > 0 else "OFF"
                    )
                    update[LightAttr.BRIGHTNESS] = int(entity.current_state * 255 / 100)
                    self.api.configured_entities.update_attributes(entity_id, update)

    async def async_register_available_entities(
        self, device_config: ZWaveDevice, device: SmartHub
    ) -> bool:
        """
        Register entities by querying the Z-Wave hub for its devices.

        This is called after the hub is connected and retrieves the actual
        devices from the Z-Wave network rather from stored config.

        :param device: The connected SmartHub instance
        :return: True if entities were registered successfully
        """
        _LOG.info(
            "📡 DRIVER: Registering available entities from Z-Wave hub: %s",
            device.identifier,
        )

        try:
            # Get lights from the hub (this queries the Z-Wave network)
            await device.get_lights()
            _LOG.info(
                "📡 DRIVER: Found %d lights on Z-Wave network", len(device.lights)
            )

            entities = []

            # Create light entities from what the hub reports
            for light_info in device.lights:
                _LOG.debug(
                    "⚡ DRIVER: Registering light: %s (node %d)",
                    light_info.name,
                    light_info.node_id,
                )
                light_entity = ZWaveLight(device.device_config, light_info, device)
                entities.append(light_entity)

            # Get covers from the hub (this queries the Z-Wave network)
            await device.get_covers()
            _LOG.info(
                "📡 DRIVER: Found %d covers on Z-Wave network", len(device.covers)
            )

            # Create cover entities from what the hub reports
            for cover_info in device.covers:
                _LOG.debug(
                    "⚡ DRIVER: Registering cover: %s (node %d) %s",
                    cover_info.name,
                    cover_info.node_id,
                    cover_info.position,
                )
                cover_entity = ZWaveCover(device.device_config, cover_info, device)
                entities.append(cover_entity)

            # Register all entities with the API
            for entity in entities:
                if self.api.available_entities.contains(entity.id):
                    _LOG.debug("⚡ DRIVER: Removing existing entity: %s", entity.id)
                    self.api.available_entities.remove(entity.id)
                _LOG.debug("⚡ DRIVER: Adding entity: %s", entity.id)
                self.api.available_entities.add(entity)
            _LOG.info(
                "✅ DRIVER: Successfully registered %d entities from Z-Wave hub",
                len(entities),
            )
            return True

        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOG.error("❌ DRIVER: Error registering entities from hub: %s", ex)
            return False


async def main():
    """Start the Remote Two/3 integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("bridge").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)

    loop = asyncio.get_running_loop()

    driver = ZWaveIntegrationDriver(
        loop=loop,
        device_class=SmartHub,
        entity_classes=[ZWaveLight, ZWaveCover],
        require_connection_before_registry=True,
    )
    # Initialize configuration manager with device callbacks
    driver.config = BaseDeviceManager(
        get_config_path(driver.api.config_dir_path),
        driver.on_device_added,
        driver.on_device_removed,
        device_class=ZWaveDevice,
    )

    # Connect to all configured Z-Wave controllers
    for device_config in list(driver.config.all()):
        await driver.async_add_configured_device(device_config)

    setup_handler = ZWaveSetupFlow.create_handler(driver.config)

    await driver.api.init("driver.json", setup_handler)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
