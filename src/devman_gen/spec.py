from __future__ import annotations

from dataclasses import dataclass, field
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
    dispatch: str | None = None
    dispatch_target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "signature": self.signature,
            "param_order": self.param_order,
            "param_kinds": self.param_kinds,
            "resource_template": self.resource_template,
            "dispatch": self.dispatch,
            "dispatch_target": self.dispatch_target,
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
            dispatch=str(raw["dispatch"]) if raw.get("dispatch") is not None else None,
            dispatch_target=str(raw["dispatch_target"]) if raw.get("dispatch_target") is not None else None,
        )


@dataclass(slots=True)
class BridgeSpec:
    module: str
    functions: list[BridgeFunctionSpec]
    default_dispatch: str = "default"
    captured_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra_imports: list[str] = field(default_factory=list)
    custom_client_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "functions": [fn.to_dict() for fn in self.functions],
            "default_dispatch": self.default_dispatch,
            "captured_types": self.captured_types,
            "extra_imports": self.extra_imports,
            "custom_client_code": self.custom_client_code,
        }

    def write_json(self, path: str | Path) -> None:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BridgeSpec":
        return cls(
            module=raw["module"],
            functions=[BridgeFunctionSpec.from_dict(fn) for fn in raw["functions"]],
            default_dispatch=str(raw.get("default_dispatch", "default")),
            captured_types=raw.get("captured_types", {}),
            extra_imports=raw.get("extra_imports", []),
            custom_client_code=raw.get("custom_client_code"),
        )

    @classmethod
    def read_json(cls, path: str | Path) -> "BridgeSpec":
        source = Path(path)
        raw = json.loads(source.read_text(encoding="utf-8"))
        return cls.from_dict(raw)
