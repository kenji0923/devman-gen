from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from pathlib import Path
import re

from enum import Enum, IntEnum
from typing import Any
from .spec import BridgeFunctionSpec, BridgeSpec


def _capture_types(module: Any, module_name: str) -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if getattr(obj, "__module__", None) != module_name:
            continue
        if not inspect.isclass(obj):
            continue
        if issubclass(obj, IntEnum):
            captured[name] = {"type": "IntEnum", "members": {m.name: m.value for m in obj}}
        elif issubclass(obj, Enum):
            captured[name] = {"type": "Enum", "members": {m.name: m.value for m in obj}}
        else:
            captured[name] = {"type": "Class"}
    return captured


_QUALIFIED_TYPE_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w+)+)\b")


def _capture_referenced_types(
    signatures: list[str],
    module_name: str,
    base_captured: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    extra_imports: set[str] = set()
    captured = dict(base_captured)
    seen: set[tuple[str, str]] = set()

    for signature in signatures:
        for qualified in _QUALIFIED_TYPE_RE.findall(signature):
            module_path, _, type_name = qualified.rpartition(".")
            if not module_path or not type_name:
                continue
            if module_path == module_name or module_path == "builtins":
                continue
            key = (module_path, type_name)
            if key in seen:
                continue
            seen.add(key)
            try:
                type_module = importlib.import_module(module_path)
                obj = getattr(type_module, type_name)
            except Exception:
                continue
            if not inspect.isclass(obj):
                continue
            extra_imports.add(module_path)
            if type_name in captured:
                continue
            if issubclass(obj, IntEnum):
                captured[type_name] = {"type": "IntEnum", "members": {m.name: m.value for m in obj}}
            elif issubclass(obj, Enum):
                captured[type_name] = {"type": "Enum", "members": {m.name: m.value for m in obj}}
            else:
                captured[type_name] = {"type": "Class"}

    return sorted(extra_imports), captured


def _default_resource_template(sig: inspect.Signature) -> str | None:
    for param in sig.parameters.values():
        if param.name in ("self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return f"{param.name}:{{{param.name}}}"
    return None


def _build_signature_from_ast(args: ast.arguments) -> tuple[str, list[str], dict[str, str]]:
    parts: list[str] = []
    param_order: list[str] = []
    param_kinds: dict[str, str] = {}

    positional = [*args.posonlyargs, *args.args]
    positional_defaults = list(args.defaults)
    positional_no_default = len(positional) - len(positional_defaults)
    default_nodes = [None] * positional_no_default + positional_defaults

    for index, arg in enumerate(positional):
        default = default_nodes[index]
        text = arg.arg
        if default is not None:
            text += "=None"
        parts.append(text)
        param_order.append(arg.arg)
        kind = "POSITIONAL_ONLY" if index < len(args.posonlyargs) else "POSITIONAL_OR_KEYWORD"
        param_kinds[arg.arg] = kind

    if args.posonlyargs:
        parts.insert(len(args.posonlyargs), "/")

    if args.vararg is not None:
        parts.append(f"*{args.vararg.arg}")
        param_order.append(args.vararg.arg)
        param_kinds[args.vararg.arg] = "VAR_POSITIONAL"
    elif args.kwonlyargs:
        parts.append("*")

    for index, arg in enumerate(args.kwonlyargs):
        default = args.kw_defaults[index]
        text = arg.arg
        if default is not None:
            text += "=None"
        parts.append(text)
        param_order.append(arg.arg)
        param_kinds[arg.arg] = "KEYWORD_ONLY"

    if args.kwarg is not None:
        parts.append(f"**{args.kwarg.arg}")
        param_order.append(args.kwarg.arg)
        param_kinds[args.kwarg.arg] = "VAR_KEYWORD"

    return f"({', '.join(parts)})", param_order, param_kinds


def _spec_from_ast_source(module_name: str) -> BridgeSpec:
    spec = importlib.util.find_spec(module_name)
    if spec is None or not spec.origin:
        raise ModuleNotFoundError(module_name)
    source_path = Path(spec.origin)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    functions: list[BridgeFunctionSpec] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            signature, param_order, param_kinds = _build_signature_from_ast(node.args)
            resource_template = f"{param_order[0]}:{{{param_order[0]}}}" if param_order else None
            functions.append(
                BridgeFunctionSpec(
                    name=node.name,
                    signature=signature,
                    param_order=param_order,
                    param_kinds=param_kinds,
                    resource_template=resource_template,
                )
            )
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for child in node.body:
                if not isinstance(child, ast.FunctionDef):
                    continue
                if child.name.startswith("_"):
                    continue
                signature, param_order, param_kinds = _build_signature_from_ast(child.args)
                if param_order and param_order[0] in ("self", "cls"):
                    param_order = param_order[1:]
                    param_kinds.pop("self", None)
                    param_kinds.pop("cls", None)
                    signature = f"({', '.join(signature.strip('()').split(', ')[1:])})" if signature != "()" else "()"
                    if signature == "()":
                        signature = "()"
                resource_template = f"{param_order[0]}:{{{param_order[0]}}}" if param_order else None
                functions.append(
                    BridgeFunctionSpec(
                        name=f"{node.name}_{child.name}",
                        signature=signature,
                        param_order=param_order,
                        param_kinds=param_kinds,
                        resource_template=resource_template,
                    )
                )

    functions.sort(key=lambda fn: fn.name)
    return BridgeSpec(module=module_name, functions=functions)


def build_spec_from_module(module_name: str) -> BridgeSpec:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return _spec_from_ast_source(module_name)
    functions: list[BridgeFunctionSpec] = []

    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        # Only capture members defined in this module
        if getattr(obj, "__module__", None) != module_name:
            continue

        if inspect.isclass(obj):
            for m_name, m_obj in inspect.getmembers(obj):
                if m_name.startswith("_"):
                    continue
                if not callable(m_obj):
                    continue
                try:
                    sig = inspect.signature(m_obj)
                except (ValueError, TypeError):
                    continue

                param_order = list(sig.parameters)
                param_kinds = {key: param.kind.name for key, param in sig.parameters.items()}

                if param_order and param_order[0] in ("self", "cls"):
                    param_order = param_order[1:]
                    param_kinds.pop("self", None)
                    param_kinds.pop("cls", None)
                    # Rebuild signature string without self/cls
                    sig_params = [
                        str(p) for p_name, p in sig.parameters.items()
                        if p_name not in ("self", "cls")
                    ]
                    sig_str = f"({', '.join(sig_params)})"
                else:
                    sig_str = str(sig)

                functions.append(
                    BridgeFunctionSpec(
                        name=f"{name}_{m_name}",
                        signature=sig_str,
                        param_order=param_order,
                        param_kinds=param_kinds,
                        resource_template=_default_resource_template(sig),
                    )
                )
        elif callable(obj):
            try:
                sig = inspect.signature(obj)
            except (ValueError, TypeError):
                continue

            functions.append(
                BridgeFunctionSpec(
                    name=name,
                    signature=str(sig),
                    param_order=list(sig.parameters),
                    param_kinds={key: param.kind.name for key, param in sig.parameters.items()},
                    resource_template=_default_resource_template(sig),
                )
            )

    functions.sort(key=lambda fn: fn.name)

    signatures = [fn.signature for fn in functions]
    extra_imports, captured_types = _capture_referenced_types(
        signatures=signatures,
        module_name=module_name,
        base_captured=_capture_types(module, module_name),
    )

    return BridgeSpec(
        module=module_name,
        functions=functions,
        captured_types=captured_types,
        extra_imports=extra_imports,
        custom_client_code=None,
    )
