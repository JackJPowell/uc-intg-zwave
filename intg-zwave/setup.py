#!/usr/bin/env python3

"""Module that includes all functions needed for the setup and reconfiguration process"""

import asyncio
import logging
from enum import IntEnum
import os
import sys

import config
from config import ZWaveConfig
from discover import ZWaveDiscovery
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationSetupError,
    RequestUserInput,
    SetupAction,
    SetupComplete,
    SetupDriver,
    SetupError,
    UserDataResponse,
)
from zwave_client import ZWaveClient

_LOG = logging.getLogger(__name__)


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3


_setup_step = SetupSteps.INIT
_cfg_add_device: bool = False

_user_input_manual = RequestUserInput(
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
            "id": "ip",
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


async def driver_setup_handler(
    msg: SetupDriver,
) -> SetupAction:
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the provided user input data.

    :param msg: the setup driver request object, either DriverSetupRequest,
                UserDataResponse or UserConfirmationResponse
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    if isinstance(msg, DriverSetupRequest):
        _setup_step = SetupSteps.INIT
        _cfg_add_device = False
        return await _handle_driver_setup(msg)
    if isinstance(msg, UserDataResponse):
        _LOG.debug("%s", msg)
        if (
            _setup_step == SetupSteps.CONFIGURATION_MODE
            and "action" in msg.input_values
        ):
            return await _handle_configuration_mode(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") != "manual"
            and "paired" in msg.input_values
        ):
            return await _handle_creation(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") != "manual"
        ):
            return await _handle_creation(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") == "manual"
        ):
            return await _handle_manual()
        _LOG.error("No user input was received for step: %s", msg)
    elif isinstance(msg, AbortDriverSetup):
        _LOG.info("Setup was aborted with code: %s", msg.error)
        _setup_step = SetupSteps.INIT

    return SetupError()


async def _handle_configuration_mode(
    msg: UserDataResponse,
) -> RequestUserInput | SetupComplete | SetupError:
    """
    Process user data response from the configuration mode screen.

    User input data:

    - ``choice`` contains identifier of selected device
    - ``action`` contains the selected action identifier

    :param msg: user input data from the configuration mode screen.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    action = msg.input_values["action"]

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    match action:
        case "add":
            _cfg_add_device = True
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case "update":
            choice = int(msg.input_values["choice"])
            msg.input_values["ip"] = config.devices.get(choice).address
            return await _handle_creation(msg)
        case "remove":
            choice = int(msg.input_values["choice"])
            if not config.devices.remove(choice):
                _LOG.warning("Could not remove device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            config.devices.store()
            return SetupComplete()
        case "reset":
            config.devices.clear()  # triggers device instance removal
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case _:
            _LOG.error("Invalid configuration action: %s", action)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    _setup_step = SetupSteps.DISCOVER
    return _user_input_manual


async def _handle_manual() -> RequestUserInput | SetupError:
    return _user_input_manual


async def _handle_discovery() -> RequestUserInput | SetupError:
    """
    Process user data response from the first setup process screen.
    """
    global _setup_step  # pylint: disable=global-statement

    discovery = ZWaveDiscovery()
    # await discovery.scan()
    if len(discovery.found_services) > 0:
        _LOG.debug("Found Z-Wave JS Server instances")

        dropdown_devices = []
        for device in discovery.found_services:
            dropdown_devices.append(
                {"id": device.address, "label": {"en": device.address}}
            )

        dropdown_devices.append({"id": "manual", "label": {"en": "Setup Manually"}})

        return RequestUserInput(
            {"en": "Discovered Z-Wave JS Server Instances"},
            [
                {
                    "id": "ip",
                    "label": {
                        "en": "Discovered Z-Wave JS Servers:",
                    },
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                },
                {
                    "id": "info",
                    "label": {
                        "en": "",
                    },
                    "field": {
                        "label": {
                            "value": {
                                "en": "Select a Z-Wave JS Server instance and press 'Next' to continue.",
                            }
                        }
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return _user_input_manual


async def _handle_driver_setup(
    msg: DriverSetupRequest,
) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver. The reconfigure flag determines the setup flow:

    - Reconfigure is True:
        show the configured devices and ask user what action to perform (add, delete, reset).
    - Reconfigure is False: clear the existing configuration and show device discovery screen.
      Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: driver setup request data, only `reconfigure` flag is of interest.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement

    reconfigure = msg.reconfigure
    _LOG.debug("Starting driver setup, reconfigure=%s", reconfigure)

    if reconfigure:
        _setup_step = SetupSteps.CONFIGURATION_MODE

        # get all configured devices for the user to choose from
        dropdown_devices = []
        for device in config.devices.all():
            dropdown_devices.append(
                {"id": str(device.identifier), "label": {"en": f"{device.name}"}}
            )

        dropdown_actions = [
            {
                "id": "add",
                "label": {
                    "en": "Add a new Z-Wave JS Server",
                },
            },
        ]

        # add remove & reset actions if there's at least one configured device
        if dropdown_devices:
            dropdown_actions.append(
                {
                    "id": "update",
                    "label": {
                        "en": "Update information for selected Z-Wave JS Server",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "remove",
                    "label": {
                        "en": "Remove selected Z-Wave JS Server",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "reset",
                    "label": {
                        "en": "Reset configuration and reconfigure",
                        "de": "Konfiguration zurücksetzen und neu konfigurieren",
                        "fr": "Réinitialiser la configuration et reconfigurer",
                    },
                },
            )
        else:
            # dummy entry if no devices are available
            dropdown_devices.append({"id": "", "label": {"en": "---"}})

        return RequestUserInput(
            {"en": "Configuration mode", "de": "Konfigurations-Modus"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                    "id": "choice",
                    "label": {
                        "en": "Configured Devices",
                        "de": "Konfigurerte Geräte",
                        "fr": "Appareils configurés",
                    },
                },
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_actions[0]["id"],
                            "items": dropdown_actions,
                        }
                    },
                    "id": "action",
                    "label": {
                        "en": "Action",
                        "de": "Aktion",
                        "fr": "Appareils configurés",
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return await _handle_discovery()


async def _handle_creation(
    msg: DriverSetupRequest,
) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver.

    :param msg: value(s) of input fields in the first setup screen.
    :return: the setup action on how to continue
    """

    ws_url = msg.input_values["ip"]

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
                    _LOG.error("Failed to connect to Z-Wave JS Server at: %s", ws_url)
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
                    controller_name = f"Z-Wave {controller_type} (SDK {sdk_version})"
                elif library_version:
                    controller_name = f"Z-Wave {controller_type} (v{library_version})"
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

                device = ZWaveConfig(
                    identifier=controller_id,
                    address=ws_url,
                    name=controller_name,
                    model=model,
                )

                config.devices.add_or_update(device)
            finally:
                await zwave_client.disconnect()

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
    _LOG.info("Setup complete")
    return SetupComplete()


def get_path() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.environ["UC_DATA_HOME"]
    return "./data"
