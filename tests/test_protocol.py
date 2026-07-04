from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json

from devman_runtime.protocol import _json_default


class Mode(Enum):
    READY = "ready"


@dataclass
class Nested:
    value: int


@dataclass
class Payload:
    mode: Mode
    nested: Nested


def test_protocol_serializes_dataclasses_and_enums() -> None:
    raw = json.dumps(
        {"status": "ok", "result": Payload(mode=Mode.READY, nested=Nested(3))},
        default=_json_default,
    )
    data = json.loads(raw)
    assert data["status"] == "ok"
    assert data["result"] == {"mode": "READY", "nested": {"value": 3}}
