# """
# Button entity functions.

# :license: Mozilla Public License Version 2.0, see LICENSE for more details.
# """

# import logging
# from typing import Any
# import asyncio
# import ucapi
# import ucapi.api as uc

# import bridge
# from config import ZWaveConfig, create_entity_id, entity_from_entity_id
# from ucapi import Button, button, EntityTypes
# from const import ZWaveSceneInfo

# _LOOP = asyncio.new_event_loop()
# asyncio.set_event_loop(_LOOP)

# _LOG = logging.getLogger(__name__)
# api = uc.IntegrationAPI(_LOOP)
# _configured_devices: dict[str, bridge.SmartHub] = {}


# class ZWaveButton(Button):
#     """Representation of a Z-Wave Button entity."""

#     def __init__(
#         self, config: ZWaveConfig, scene_info: ZWaveSceneInfo, get_device: Any = None
#     ):
#         """Initialize the class."""
#         _LOG.debug("Z-Wave Button init")
#         entity_id = create_entity_id(
#             config.identifier, scene_info.scene_id, EntityTypes.BUTTON
#         )
#         self.config = config
#         self.get_device = get_device

#         super().__init__(
#             entity_id,
#             scene_info.name,
#             cmd_handler=self.button_cmd_handler,
#         )

#     async def button_cmd_handler(
#         self, entity: Button, cmd_id: str, params: dict[str, Any] | None
#     ) -> ucapi.StatusCodes:
#         """
#         Button entity command handler.

#         Called by the integration-API if a command is sent to a configured button entity.

#         :param entity: button entity
#         :param cmd_id: command
#         :param params: optional command parameters
#         :return: status code of the command. StatusCodes.OK if the command succeeded.
#         """
#         _LOG.info(
#             "Got %s command request: %s %s", entity.id, cmd_id, params if params else ""
#         )
#         device = self.get_device(self.config.identifier)

#         try:
#             match cmd_id:
#                 case button.Commands.PUSH:
#                     await device.activate_scene(
#                         scene_id=entity_from_entity_id(entity.id)
#                     )

#         except Exception as ex:  # pylint: disable=broad-except
#             _LOG.error("Error executing command %s: %s", cmd_id, ex)
#             return ucapi.StatusCodes.BAD_REQUEST
#         return ucapi.StatusCodes.OK
