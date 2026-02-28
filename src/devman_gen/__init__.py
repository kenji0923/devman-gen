"""devman-gen package."""

from .generator import generate_bridge_package
from .introspect import build_spec_from_module
from .spec import BridgeFunctionSpec, BridgeSpec

__all__ = [
    "generate_bridge_package",
    "build_spec_from_module",
    "BridgeFunctionSpec",
    "BridgeSpec",
]
