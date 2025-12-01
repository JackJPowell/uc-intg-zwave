"""
This module implements the Z-Wave constants for the Remote Two/3 integration driver.
"""

from dataclasses import dataclass


@dataclass
class ZWaveDevice:
    """Z-Wave controller configuration."""

    identifier: str
    """Unique identifier of the controller."""
    address: str
    """WebSocket URL of Z-Wave JS Server (e.g., ws://localhost:3000)"""
    name: str
    """Name of the controller."""
    model: str
    """Model name of the controller."""


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
    position: int
    type: str
    name: str
    model: str
