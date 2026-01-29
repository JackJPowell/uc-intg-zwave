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
from const import ZWaveConfig
from cover import ZWaveCover
from light import ZWaveLight
from setup import ZWaveSetupFlow
from ucapi_framework import BaseConfigManager, BaseIntegrationDriver, get_config_path

_LOG = logging.getLogger("driver")


async def main():
    """Start the Remote Two/3 integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("bridge").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)

    driver = BaseIntegrationDriver(
        device_class=SmartHub,
        entity_classes=[
            lambda cfg, dev: [ZWaveLight(cfg, light, dev) for light in dev.lights],
            lambda cfg, dev: [ZWaveCover(cfg, cover, dev) for cover in dev.covers],
        ],
        require_connection_before_registry=True,
    )
    # Initialize configuration manager with device callbacks
    driver.config_manager = BaseConfigManager(
        get_config_path(driver.api.config_dir_path),
        driver.on_device_added,
        driver.on_device_removed,
        config_class=ZWaveConfig,
    )

    await driver.register_all_device_instances()
    setup_handler = ZWaveSetupFlow.create_handler(driver)
    await driver.api.init("driver.json", setup_handler)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
