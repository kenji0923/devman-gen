"""devman-gen package."""

from .generator import generate_bridge_packages
from .introspect import build_spec_from_module
from .spec import BridgeFunctionSpec, BridgeSpec

__all__ = [
    "generate_bridge_packages",
    "build_spec_from_module",
    "BridgeFunctionSpec",
    "BridgeSpec",
]
