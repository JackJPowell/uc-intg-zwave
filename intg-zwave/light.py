"""
Light entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import ucapi
from bridge import SmartHub
from const import ZWaveConfig, ZWaveLightInfo
from ucapi import EntityTypes, light
from ucapi.light import Attributes, Light, States
from ucapi_framework import create_entity_id, Entity

_LOG = logging.getLogger(__name__)


class ZWaveLight(Light, Entity):
    """Representation of a Z-Wave Light entity."""

    def __init__(
        self,
        config: ZWaveConfig,
        light_info: ZWaveLightInfo,
        device: SmartHub,
    ):
        """Initialize the class."""
        _LOG.debug("Z-Wave Light init")
        self.config = config
        self.features = [
            light.Features.ON_OFF,
            light.Features.TOGGLE,
            light.Features.DIM,
        ]

        self.light: ZWaveLightInfo | None = None

        self.device: SmartHub | None = device
        if self.device:
            self.light = next(
                (
                    entity
                    for entity in self.device.lights
                    if entity.node_id == light_info.node_id
                ),
                None,
            )
        else:
            self.light = light_info

        # Check if device supports dimming based on type
        if (
            "switch" in light_info.type.lower()
            and "multilevel" not in light_info.type.lower()
        ):
            # Binary switch, no dimming
            if light.Features.DIM in self.features:
                self.features.remove(light.Features.DIM)

        super().__init__(
            create_entity_id(
                entity_type=EntityTypes.LIGHT,
                device_id=config.identifier,
                sub_device_id=str(light_info.node_id),
            ),
            light_info.name,
            self.features,
            attributes={
                Attributes.STATE: States.OFF,
                Attributes.BRIGHTNESS: 0,
            },
            cmd_handler=self.cmd_handler,
        )

    # pylint: disable=too-many-statements
    async def cmd_handler(
        self,
        entity: Light,
        cmd_id: str,
        params: dict[str, Any] | None,
        _: Any | None = None,
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

        try:
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

                    await self.device.control_light(
                        self.light.node_id, 99 if brightness is None else brightness
                    )
                case light.Commands.OFF:
                    _LOG.debug("Sending OFF command to Light")
                    await self.device.control_light(self.light.node_id, 0)
                case light.Commands.TOGGLE:
                    _LOG.debug("Sending TOGGLE command to Light")
                    await self.device.toggle_light(self.light.node_id)

            # Get updated attributes from device and update entity
            if entity.id in self.device.light_attributes:
                self.update(self.device.get_device_attributes(entity.id))

        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK
