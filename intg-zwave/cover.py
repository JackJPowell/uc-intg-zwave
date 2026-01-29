"""
Cover entity functions.

:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import ucapi
from bridge import SmartHub
from const import ZWaveCoverInfo, ZWaveConfig
from ucapi import Cover, EntityTypes, cover
from ucapi_framework import create_entity_id, Entity

_LOG = logging.getLogger(__name__)


class ZWaveCover(Cover, Entity):
    """Representation of a Z-Wave Cover entity."""

    def __init__(
        self,
        config: ZWaveConfig,
        cover_info: ZWaveCoverInfo,
        device: SmartHub,
    ):
        """Initialize the class."""
        _LOG.debug("Z-Wave Cover init")
        self.config = config
        self.cover: ZWaveCoverInfo | None = None

        self.device: SmartHub | None = device
        if self.device:
            self.cover = next(
                (
                    entity
                    for entity in self.device.covers
                    if entity.node_id == cover_info.node_id
                ),
                None,
            )
        else:
            self.cover = cover_info

        super().__init__(
            create_entity_id(
                entity_type=EntityTypes.COVER,
                device_id=config.identifier,
                sub_device_id=str(cover_info.node_id),
            ),
            self.cover.name,
            features=[
                cover.Features.OPEN,
                cover.Features.CLOSE,
                cover.Features.POSITION,
            ],
            attributes={
                cover.Attributes.STATE: "OPEN"
                if self.cover.position > 50
                else "CLOSED",
                cover.Attributes.POSITION: 100
                if self.cover.position == 99
                else self.cover.position,
            },
            device_class=cover.DeviceClasses.SHADE,
            cmd_handler=self.cover_cmd_handler,
        )

    async def cover_cmd_handler(
        self,
        entity: Cover,
        cmd_id: str,
        params: dict[str, Any] | None,
        _: Any | None = None,
    ) -> ucapi.StatusCodes:
        """
        Cover entity command handler.

        Called by the integration-API if a command is sent to a configured cover entity.

        :param entity: cover entity
        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command. StatusCodes.OK if the command succeeded.
        """
        _LOG.info(
            "Got %s command request: %s %s", entity.id, cmd_id, params if params else ""
        )

        try:
            match cmd_id:
                case cover.Commands.OPEN:
                    await self.device.control_cover(
                        cover_id=self.cover.node_id, position=100
                    )
                case cover.Commands.CLOSE:
                    await self.device.control_cover(
                        cover_id=self.cover.node_id, position=0
                    )
                case cover.Commands.STOP:
                    return ucapi.StatusCodes.BAD_REQUEST
                case cover.Commands.POSITION:
                    if params and "position" in params:
                        position = params["position"]
                        await self.device.control_cover(
                            cover_id=self.cover.node_id,
                            position=position,
                        )

            # Get updated attributes from device and update entity
            if entity.id in self.device.cover_attributes:
                self.update(self.device.get_device_attributes(entity.id), force=True)

        except Exception as ex:  # pylint: disable=broad-except
            _LOG.error("Error executing command %s: %s", cmd_id, ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK
