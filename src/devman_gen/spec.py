from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BridgeFunctionSpec:
    name: str
    signature: str
    param_order: list[str]
    param_kinds: dict[str, str]
    resource_template: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "signature": self.signature,
            "param_order": self.param_order,
            "param_kinds": self.param_kinds,
            "resource_template": self.resource_template,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BridgeFunctionSpec":
        param_order = list(raw["param_order"])
        param_kinds = dict(raw.get("param_kinds", {}))
        for name in param_order:
            param_kinds.setdefault(name, "POSITIONAL_OR_KEYWORD")
        return cls(
            name=raw["name"],
            signature=raw["signature"],
            param_order=param_order,
            param_kinds=param_kinds,
            resource_template=raw.get("resource_template"),
        )


@dataclass(slots=True)
class BridgeSpec:
    module: str
    functions: list[BridgeFunctionSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "functions": [fn.to_dict() for fn in self.functions],
        }

    def write_json(self, path: str | Path) -> None:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BridgeSpec":
        return cls(
            module=raw["module"],
            functions=[BridgeFunctionSpec.from_dict(fn) for fn in raw["functions"]],
        )

    @classmethod
    def read_json(cls, path: str | Path) -> "BridgeSpec":
        source = Path(path)
        raw = json.loads(source.read_text(encoding="utf-8"))
        return cls.from_dict(raw)
