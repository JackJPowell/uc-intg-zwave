"""
Light entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any
import ucapi
from config import ZWaveConfig, create_entity_id
from ucapi import EntityTypes, light
from ucapi.light import Attributes, Light, States
from const import ZWaveLightInfo
import bridge

_LOG = logging.getLogger(__name__)
_configured_devices: dict[str, bridge.SmartHub] = {}


class ZWaveLight(Light):
    """Representation of a Z-Wave Light entity."""

    def __init__(
        self,
        config_device: ZWaveConfig,
        light_info: ZWaveLightInfo,
        get_device: Any = None,
    ):
        """Initialize the class."""
        _LOG.debug("Z-Wave Light init")
        entity_id = create_entity_id(
            device_id=config_device.identifier,
            entity_id=str(light_info.node_id),
            entity_type=EntityTypes.LIGHT,
        )
        self.config = config_device
        self.get_device = get_device
        self.features = [
            light.Features.ON_OFF,
            light.Features.TOGGLE,
            light.Features.DIM,
        ]

        # Check if device supports dimming based on type
        if (
            "switch" in light_info.type.lower()
            and "multilevel" not in light_info.type.lower()
        ):
            # Binary switch, no dimming
            if light.Features.DIM in self.features:
                self.features.remove(light.Features.DIM)

        super().__init__(
            entity_id,
            light_info.name,
            self.features,
            attributes={
                Attributes.STATE: States.ON
                if light_info.brightness > 0
                else States.OFF,
                Attributes.BRIGHTNESS: "100"
                if light_info.brightness == 99
                else str(light_info.brightness),
            },
            cmd_handler=self.cmd_handler,
        )

    # pylint: disable=too-many-statements
    async def cmd_handler(
        self, entity: Light, cmd_id: str, params: dict[str, Any] | None
    ) -> ucapi.StatusCodes:
        """
        Z-Wave light entity command handler.

        Called by the integration-API if a command is sent to a configured Z-Wave light entity.

        :param entity: Z-Wave light entity
        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command. StatusCodes.OK if the command succeeded.
        """
        _LOG.info(
            "Got %s command request: %s %s", entity.id, cmd_id, params if params else ""
        )
        device: bridge.SmartHub = self.get_device(self.config.identifier)

        try:
            identifier = entity.id.split(".", 2)[2]
            brightness = None
            match cmd_id:
                case light.Commands.ON:
                    if params and Attributes.BRIGHTNESS in params:
                        brightness = int(params[Attributes.BRIGHTNESS] / 255 * 100)
                        if brightness < 0 or brightness > 100:
                            _LOG.error(
                                "Invalid brightness value %s for command %s",
                                brightness,
                                cmd_id,
                            )
                            return ucapi.StatusCodes.BAD_REQUEST

                    res = await device.control_light(
                        identifier, 99 if brightness is None else brightness
                    )
                case light.Commands.OFF:
                    _LOG.debug("Sending OFF command to Light")
                    res = await device.control_light(identifier, 0)
                case light.Commands.TOGGLE:
                    _LOG.debug("Sending TOGGLE command to Light")
                    res = await device.toggle_light(identifier)

        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("Command %s executed successfully: %s", cmd_id, res)
        return ucapi.StatusCodes.OK
