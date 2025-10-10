"""
This module implements the Z-Wave constants for the Remote Two/3 integration driver.
"""

from dataclasses import dataclass


@dataclass
class ZWaveLightInfo:
    device_id: str
    node_id: int
    current_state: int
    brightness: int
    type: str
    name: str
    model: str


@dataclass
class ZWaveCoverInfo:
    device_id: str
    node_id: int
    current_state: int
    type: str
    name: str
    model: str


@dataclass
class ZWaveSceneInfo:
    scene_id: str
    name: str
