from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat

from .spec import BridgeSpec


def _prepend_param(signature: str, name: str) -> str:
    inner = signature.strip()[1:-1].strip()
    if not inner:
        return f"({name})"
    return f"({name}, {inner})"


def _client_source(spec: BridgeSpec) -> str:
    param_order = {fn.name: fn.param_order for fn in spec.functions}
    param_kinds = {fn.name: fn.param_kinds for fn in spec.functions}
    resource_templates = {fn.name: fn.resource_template for fn in spec.functions}

    device_functions = {
        fn.name[len("Device_") :]: fn for fn in spec.functions if fn.name.startswith("Device_")
    }

    lines: list[str] = []
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import os")
    lines.append("from typing import Any")
    lines.append("")
    lines.append("from devman_gen.runtime.client import ManagerClient")
    lines.append("")

    if spec.module == "caen_libs.caenhvwrapper":
        lines.append("try:")
        lines.append("    from caen_libs._caenhvwrappertypes import *")
        lines.append("    from caen_libs.caenhvwrapperflags import *")
        lines.append("except Exception:")
        lines.append("    pass")
        lines.append("")

    lines.append(f"_PARAM_ORDER = {pformat(param_order, indent=2, sort_dicts=True)}")
    lines.append(f"_PARAM_KINDS = {pformat(param_kinds, indent=2, sort_dicts=True)}")
    lines.append(f"_RESOURCE_TEMPLATES = {pformat(resource_templates, indent=2, sort_dicts=True)}")
    lines.append("")
    lines.append("_CLIENT = ManagerClient(")
    lines.append("    host=os.getenv(\"DEVMAN_HOST\", \"127.0.0.1\"),")
    lines.append("    port=int(os.getenv(\"DEVMAN_PORT\", \"50250\")),")
    lines.append("    client_name=os.getenv(\"DEVMAN_CLIENT\", \"anonymous\"),")
    lines.append(")")
    lines.append("")
    lines.append("")
    lines.append("def configure_connection(host: str, port: int, client_name: str, timeout: float = 5.0) -> None:")
    lines.append("    global _CLIENT")
    lines.append("    _CLIENT = ManagerClient(host=host, port=port, client_name=client_name, timeout=timeout)")
    lines.append("")
    lines.append("")
    lines.append("def acquire(resource: str) -> bool:")
    lines.append("    return _CLIENT.acquire(resource)")
    lines.append("")
    lines.append("")
    lines.append("def release(resource: str) -> bool:")
    lines.append("    return _CLIENT.release(resource)")
    lines.append("")
    lines.append("")
    lines.append("def _pack_call_args(function: str, local_vars: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:")
    lines.append("    order = _PARAM_ORDER[function]")
    lines.append("    kinds = _PARAM_KINDS[function]")
    lines.append("    args: list[Any] = []")
    lines.append("    kwargs: dict[str, Any] = {}")
    lines.append("    for name in order:")
    lines.append("        if name not in local_vars:")
    lines.append("            continue")
    lines.append("        kind = kinds.get(name, 'POSITIONAL_OR_KEYWORD')")
    lines.append("        value = local_vars[name]")
    lines.append("        if kind == 'VAR_POSITIONAL':")
    lines.append("            args.extend(list(value))")
    lines.append("        elif kind == 'VAR_KEYWORD':")
    lines.append("            kwargs.update(dict(value))")
    lines.append("        elif kind == 'KEYWORD_ONLY':")
    lines.append("            kwargs[name] = value")
    lines.append("        else:")
    lines.append("            args.append(value)")
    lines.append("    return args, kwargs")
    lines.append("")
    lines.append("")
    lines.append("def _resources_for(function: str, local_vars: dict[str, Any]) -> list[str]:")
    lines.append("    template = _RESOURCE_TEMPLATES.get(function)")
    lines.append("    if not template:")
    lines.append("        return []")
    lines.append("    context = dict(local_vars)")
    lines.append("    context.pop('kwargs', None)")
    lines.append("    return [template.format(**context)]")
    lines.append("")

    for fn in spec.functions:
        lines.append("")
        lines.append(f"def {fn.name}{fn.signature}:")
        lines.append("    _locals = locals()")
        lines.append(f"    _args, _kwargs = _pack_call_args(\"{fn.name}\", _locals)")
        lines.append(f"    _resources = _resources_for(\"{fn.name}\", _locals)")
        lines.append(f"    return _CLIENT.invoke(\"{fn.name}\", _args, _kwargs, _resources)")

    if device_functions:
        lines.append("")
        lines.append("")
        lines.append("class Device:")
        lines.append("    def __init__(self, handle: str) -> None:")
        lines.append("        self._handle = handle")

        if "open" in device_functions:
            open_fn = device_functions["open"]
            lines.append("")
            lines.append("    @classmethod")
            lines.append(f"    def open{_prepend_param(open_fn.signature, 'cls')}:")
            lines.append("        _locals = locals()")
            lines.append("        _locals.pop('cls', None)")
            lines.append("        _args, _kwargs = _pack_call_args('Device_open', _locals)")
            lines.append("        _resources = _resources_for('Device_open', _locals)")
            lines.append("        _result = _CLIENT.invoke('Device_open', _args, _kwargs, _resources)")
            lines.append("        if isinstance(_result, dict) and '__devman_handle__' in _result:")
            lines.append("            return cls(str(_result['__devman_handle__']))")
            lines.append("        raise RuntimeError('manager did not return a device handle')")

        for method_name, fn in sorted(device_functions.items()):
            if method_name == "open":
                continue
            lines.append("")
            lines.append(f"    def {method_name}{_prepend_param(fn.signature, 'self')}:")
            lines.append("        _locals = locals()")
            lines.append("        _locals.pop('self', None)")
            lines.append(f"        _args, _kwargs = _pack_call_args('Device_{method_name}', _locals)")
            lines.append(f"        _resources = _resources_for('Device_{method_name}', _locals)")
            lines.append(
                f"        return _CLIENT.invoke('Device_{method_name}', _args, _kwargs, _resources, handle=self._handle)"
            )

        if "close" in device_functions:
            lines.append("")
            lines.append("    def __enter__(self):")
            lines.append("        return self")
            lines.append("")
            lines.append("    def __exit__(self, exc_type, exc_value, traceback) -> None:")
            lines.append("        self.close()")

    if spec.module == "caen_libs.caenhvwrapper":
        lines.append("")
        lines.append("")
        lines.append("class _LibProxy:")
        lines.append("    def sw_release(self) -> str:")
        lines.append("        try:")
        lines.append("            value = _CLIENT.invoke('lib.sw_release', [], {}, [])")
        lines.append("            return str(value)")
        lines.append("        except Exception:")
        lines.append("            return 'managed'")
        lines.append("")
        lines.append("lib = _LibProxy()")

    lines.append("")
    return "\n".join(lines)


def _server_source(spec: BridgeSpec) -> str:
    function_map = {
        fn.name: {
            "name": fn.name,
            "param_order": fn.param_order,
            "param_kinds": fn.param_kinds,
            "resource_template": fn.resource_template,
        }
        for fn in spec.functions
    }

    lines: list[str] = []
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import argparse")
    lines.append("import os")
    lines.append("")
    lines.append("from devman_gen.runtime.server import RuntimeFunctionSpec, serve_manager")
    lines.append("")
    lines.append(f"FUNCTIONS = {pformat(function_map, indent=2, sort_dicts=True)}")
    lines.append("")
    lines.append("")
    lines.append("def _runtime_specs() -> dict[str, RuntimeFunctionSpec]:")
    lines.append("    return {")
    lines.append("        name: RuntimeFunctionSpec(")
    lines.append("            name=data['name'],")
    lines.append("            param_order=list(data['param_order']),")
    lines.append("            param_kinds=dict(data.get('param_kinds', {})),")
    lines.append("            resource_template=data['resource_template'],")
    lines.append("        )")
    lines.append("        for name, data in FUNCTIONS.items()")
    lines.append("    }")
    lines.append("")
    lines.append("")
    lines.append("def main() -> None:")
    lines.append("    parser = argparse.ArgumentParser(description='Run devman manager server')")
    lines.append("    parser.add_argument('--backend-module', default=os.getenv('DEVMAN_BACKEND_MODULE'), required=False)")
    lines.append("    parser.add_argument('--host', default=os.getenv('DEVMAN_HOST', '127.0.0.1'))")
    lines.append("    parser.add_argument('--port', type=int, default=int(os.getenv('DEVMAN_PORT', '50250')))")
    lines.append("    parser.add_argument('--db', default=os.getenv('DEVMAN_DB', './ownership.db'))")
    lines.append("    args = parser.parse_args()")
    lines.append("    if not args.backend_module:")
    lines.append("        parser.error('--backend-module or DEVMAN_BACKEND_MODULE is required')")
    lines.append("    serve_manager(")
    lines.append("        backend_module=args.backend_module,")
    lines.append("        host=args.host,")
    lines.append("        port=args.port,")
    lines.append("        db_path=args.db,")
    lines.append("        functions=_runtime_specs(),")
    lines.append("    )")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    main()")
    lines.append("")
    return "\n".join(lines)


def generate_bridge_package(spec: BridgeSpec, output_dir: str | Path, package_name: str) -> Path:
    root = Path(output_dir)
    package_dir = root / package_name
    package_dir.mkdir(parents=True, exist_ok=True)

    (package_dir / "__init__.py").write_text(
        "from .client import *\n"
        "\n"
        "__all__ = [name for name in globals() if not name.startswith('_')]\n",
        encoding="utf-8",
    )
    (package_dir / "client.py").write_text(_client_source(spec), encoding="utf-8")
    (package_dir / "server.py").write_text(_server_source(spec), encoding="utf-8")
    (package_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2) + "\n", encoding="utf-8")

    return package_dir
