#!/usr/bin/env python3

"""Module that includes all functions needed for the setup and reconfiguration process"""

import asyncio
import logging
from typing import Any

from const import ZWaveDevice
from ucapi import IntegrationSetupError, RequestUserInput, SetupError
from ucapi_framework import BaseSetupFlow
from zwave_client import ZWaveClient

_LOG = logging.getLogger(__name__)


_MANUAL_INPUT_SCHEMA = RequestUserInput(
    {"en": "Z-Wave Setup"},
    [
        {
            "id": "info",
            "label": {
                "en": "Setup your Z-Wave JS Server",
            },
            "field": {
                "label": {
                    "value": {
                        "en": (
                            "Please supply the WebSocket URL of your Z-Wave JS Server (e.g., ws://192.168.1.100:3000)."
                        ),
                    }
                }
            },
        },
        {
            "field": {"text": {"value": "ws://"}},
            "id": "address",
            "label": {
                "en": "WebSocket URL",
            },
        },
        {
            "id": "setup_info",
            "label": {
                "en": "",
            },
            "field": {
                "label": {
                    "value": {
                        "en": "Make sure your Z-Wave JS Server is running and accessible at the provided URL.",
                    }
                }
            },
        },
    ],
)


class ZwaveSetupFlow(BaseSetupFlow[ZWaveDevice]):
    """
    Setup flow for Z-Wave integration.

    Handles Z-Wave configuration through manual entry.
    """

    def get_manual_entry_form(self) -> RequestUserInput:
        """
        Get the manual entry form for Yamaha AVR setup.

        :return: RequestUserInput for manual entry
        """
        return _MANUAL_INPUT_SCHEMA

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> ZWaveDevice | RequestUserInput:
        """
        Start driver setup.

        Initiated by Remote Two to set up the driver.

        :param msg: value(s) of input fields in the first setup screen.
        :return: the setup action on how to continue
        """

        ws_url = input_values["address"]

        if ws_url != "":
            # Validate WebSocket URL format
            if not ws_url.startswith("ws://") and not ws_url.startswith("wss://"):
                _LOG.error(
                    "The entered WebSocket URL %s is not valid. Must start with ws:// or wss://",
                    ws_url,
                )
                return SetupError(IntegrationSetupError.NOT_FOUND)

            _LOG.info("Entered WebSocket URL: %s", ws_url)

            try:
                zwave_client = ZWaveClient(ws_url)
                try:
                    success = await zwave_client.connect()
                    if not success:
                        _LOG.error(
                            "Failed to connect to Z-Wave JS Server at: %s", ws_url
                        )
                        return SetupError(IntegrationSetupError.CONNECTION_REFUSED)

                    # Get controller information
                    controller_info = zwave_client.get_controller_info()
                    _LOG.info("Z-Wave Controller info: %s", controller_info)

                    # Get devices from Z-Wave network
                    devices = zwave_client.get_devices()
                    _LOG.debug("Found %d Z-Wave devices", len(devices))

                    # Generate identifier from controller's home_id (unique to each Z-Wave network)
                    home_id = controller_info.get("home_id")
                    if home_id:
                        # Home ID is a unique identifier for the Z-Wave network
                        controller_id = f"zwave_{home_id:08x}"
                        _LOG.debug("Using Home ID as identifier: %s", controller_id)
                    else:
                        # Fallback to URL-based identifier if home_id not available
                        controller_id = (
                            ws_url.replace("ws://", "")
                            .replace("wss://", "")
                            .replace(":", "_")
                            .replace("/", "_")
                        )
                        _LOG.warning(
                            "Home ID not available, using URL-based identifier: %s",
                            controller_id,
                        )

                    # Generate a friendly name
                    sdk_version = controller_info.get("sdk_version", "")
                    library_version = controller_info.get("library_version", "")
                    controller_type = controller_info.get("type_name", "Controller")

                    if sdk_version:
                        controller_name = (
                            f"Z-Wave {controller_type} (SDK {sdk_version})"
                        )
                    elif library_version:
                        controller_name = (
                            f"Z-Wave {controller_type} (v{library_version})"
                        )
                    else:
                        controller_name = f"Z-Wave {controller_type}"

                    # Generate model information
                    manufacturer_id = controller_info.get("manufacturer_id")
                    product_type = controller_info.get("product_type")
                    product_id = controller_info.get("product_id")

                    if manufacturer_id and product_type and product_id:
                        model = f"Z-Wave Controller (Mfr: {manufacturer_id:04x}, Type: {product_type:04x}, ID: {product_id:04x})"
                    else:
                        model = "Z-Wave JS Server"

                    return ZWaveDevice(
                        identifier=controller_id,
                        address=ws_url,
                        name=controller_name,
                        model=model,
                    )

                finally:
                    await zwave_client.disconnect()
                    # Give the Z-Wave JS Server a moment to clean up the WebSocket connection
                    # before the driver attempts to reconnect. This prevents race conditions
                    # where the server hasn't fully released resources yet.
                    await asyncio.sleep(0.3)

            except Exception as ex:  # pylint: disable=broad-exception-caught
                _LOG.error(
                    "Unable to connect to Z-Wave JS Server at: %s. Exception: %s",
                    ws_url,
                    ex,
                )
                _LOG.info(
                    "Please check if you entered the correct WebSocket URL and that Z-Wave JS Server is running"
                )
                return SetupError(IntegrationSetupError.CONNECTION_REFUSED)
        else:
            _LOG.info("No WebSocket URL entered")
            return SetupError(IntegrationSetupError.OTHER)
