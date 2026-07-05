from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat
import shutil

from .spec import BridgeSpec


def _prepend_param(signature: str, name: str) -> str:
    inner = signature.strip()[1:-1].strip()
    if not inner:
        return f"({name})"
    return f"({name}, {inner})"


def _clean_signature(signature: str) -> str:
    sig = signature
    if "->" in sig:
        sig = sig.split("->")[0].strip()
    return sig


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
    lines.append("import itertools")
    lines.append("import os")
    lines.append("import re")
    lines.append("from typing import Any")
    lines.append("")
    lines.append("from devman_runtime.client import ManagerClient")
    lines.append("")

    lines.append("try:")
    lines.append(f"    from {spec.module} import *")
    for extra in spec.extra_imports:
        lines.append(f"    from {extra} import *")
    lines.append("except Exception:")
    if spec.captured_types:
        lines.append("    from enum import Enum, IntEnum")
        for type_name, type_info in spec.captured_types.items():
            if type_name in ("Enum", "IntEnum"):
                continue
            if type_info["type"] == "IntEnum":
                lines.append("")
                lines.append(f"    class {type_name}(IntEnum):")
                for member_name, member_value in type_info["members"].items():
                    lines.append(f"        {member_name} = {member_value}")
            elif type_info["type"] == "Enum":
                lines.append("")
                lines.append(f"    class {type_name}(Enum):")
                for member_name, member_value in type_info["members"].items():
                    lines.append(f"        {member_name} = {member_value!r}")
            else:
                lines.append("")
                lines.append(f"    class {type_name}:")
                lines.append("        pass")
    else:
        lines.append("    pass")
    lines.append("")

    lines.append(f"_PARAM_ORDER = {pformat(param_order, indent=2, sort_dicts=True)}")
    lines.append(f"_PARAM_KINDS = {pformat(param_kinds, indent=2, sort_dicts=True)}")
    lines.append(f"_RESOURCE_TEMPLATES = {pformat(resource_templates, indent=2, sort_dicts=True)}")
    lines.append("")
    lines.append("def _default_client_name() -> str:")
    lines.append("    name = os.getenv('DEVMAN_CLIENT')")
    lines.append("    if name is None or not str(name).strip():")
    lines.append("        raise RuntimeError('DEVMAN_CLIENT is required')")
    lines.append("    return str(name).strip()")
    lines.append("")
    lines.append("_CLIENT = ManagerClient(")
    lines.append("    host=os.getenv('DEVMAN_HOST', '127.0.0.1'),")
    lines.append("    port=int(os.getenv('DEVMAN_PORT', '50250')),")
    lines.append("    client_name=_default_client_name(),")
    lines.append(")")
    lines.append("")

    lines.append("def configure_connection(host: str, port: int, client_name: str, timeout: float = 5.0) -> None:")
    lines.append("    global _CLIENT")
    lines.append("    _CLIENT = ManagerClient(host=host, port=port, client_name=client_name, timeout=timeout)")
    lines.append("")
    lines.append("def acquire(resource: str) -> bool:")
    lines.append("    return _CLIENT.acquire(resource)")
    lines.append("")
    lines.append("def release(resource: str) -> bool:")
    lines.append("    return _CLIENT.release(resource)")
    lines.append("")
    lines.append("def owner_of(resource: str) -> str | None:")
    lines.append("    return _CLIENT.owner_of(resource)")
    lines.append("")
    lines.append("def owners_of(resources: list[str]) -> dict[str, str | None]:")
    lines.append("    return _CLIENT.owners_of(resources)")
    lines.append("")
    lines.append("def set_link_groups(groups: list[list[str]]) -> int:")
    lines.append("    return _CLIENT.set_link_groups(groups)")
    lines.append("")
    lines.append("def list_link_groups() -> dict[str, list[list[str]]]:")
    lines.append("    return _CLIENT.list_link_groups()")
    lines.append("")
    lines.append("def connect(force: bool = False) -> None:")
    lines.append("    _CLIENT.connect(force=force)")
    lines.append("")
    lines.append("def disconnect() -> None:")
    lines.append("    _CLIENT.disconnect()")
    lines.append("")
    lines.append("def close() -> None:")
    lines.append("    _CLIENT.close()")
    lines.append("")

    lines.append("_EXPAND_FIELD_RE = re.compile(r'\\{([A-Za-z_]\\w*)\\[\\]\\}')")
    lines.append("")
    lines.append("def _expand_resource_template(template: str, context: dict[str, Any]) -> list[str]:")
    lines.append("    expand_fields = _EXPAND_FIELD_RE.findall(template)")
    lines.append("    if not expand_fields:")
    lines.append("        return [template.format(**context)]")
    lines.append("    ordered_fields = list(dict.fromkeys(expand_fields))")
    lines.append("    normalized = template")
    lines.append("    values_by_field: list[list[Any]] = []")
    lines.append("    for field in ordered_fields:")
    lines.append("        normalized = normalized.replace(f'{{{field}[]}}', f'{{{field}}}')")
    lines.append("        raw = context.get(field)")
    lines.append("        if raw is None:")
    lines.append("            return []")
    lines.append("        if isinstance(raw, (str, bytes, bytearray)):")
    lines.append("            values = [raw]")
    lines.append("        else:")
    lines.append("            try:")
    lines.append("                values = list(raw)")
    lines.append("            except TypeError:")
    lines.append("                values = [raw]")
    lines.append("        if not values:")
    lines.append("            return []")
    lines.append("        values_by_field.append(values)")
    lines.append("    resources: list[str] = []")
    lines.append("    for combo in itertools.product(*values_by_field):")
    lines.append("        local_context = dict(context)")
    lines.append("        for field, value in zip(ordered_fields, combo):")
    lines.append("            local_context[field] = value")
    lines.append("        resources.append(normalized.format(**local_context))")
    lines.append("    return resources")
    lines.append("")

    lines.append("def _pack_call_args(function: str, local_vars: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:")
    lines.append("    order = _PARAM_ORDER[function]")
    lines.append("    kinds = _PARAM_KINDS[function]")
    lines.append("    args: list[Any] = []")
    lines.append("    kwargs: dict[str, Any] = {}")
    lines.append("    for name in order:")
    lines.append("        if name not in local_vars or name in ('self', 'cls'):")
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

    lines.append("def _resources_for(function: str, local_vars: dict[str, Any]) -> list[str]:")
    lines.append("    context = dict(local_vars)")
    lines.append("    context.pop('kwargs', None)")
    lines.append("    template = _RESOURCE_TEMPLATES.get(function)")
    lines.append("    if not template:")
    lines.append("        return []")
    lines.append("    return _expand_resource_template(template, context)")

    for fn in spec.functions:
        sig = _clean_signature(fn.signature)
        lines.append("")
        lines.append(f"def {fn.name}{sig}:")
        lines.append("    _locals = locals()")
        lines.append(f"    _args, _kwargs = _pack_call_args('{fn.name}', _locals)")
        lines.append(f"    _resources = _resources_for('{fn.name}', _locals)")
        lines.append(f"    return _CLIENT.invoke('{fn.name}', _args, _kwargs, _resources)")

    if device_functions:
        lines.append("")
        lines.append("class Device:")
        lines.append("    def __init__(self, handle: str) -> None:")
        lines.append("        self._handle = handle")

        if "open" in device_functions:
            open_fn = device_functions["open"]
            lines.append("")
            lines.append("    @classmethod")
            lines.append(f"    def open{_prepend_param(_clean_signature(open_fn.signature), 'cls')}:")
            lines.append("        _locals = locals()")
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
            lines.append(f"    def {method_name}{_prepend_param(_clean_signature(fn.signature), 'self')}:")
            lines.append("        _locals = locals()")
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

    if spec.custom_client_code:
        lines.append("")
        lines.append(spec.custom_client_code)

    lines.append("")
    return "\n".join(lines)


def _server_source(spec: BridgeSpec) -> str:
    default_dispatch = spec.default_dispatch
    function_map = {
        fn.name: {
            "name": fn.name,
            "param_order": fn.param_order,
            "param_kinds": fn.param_kinds,
            "resource_template": fn.resource_template,
            "dispatch": fn.dispatch if fn.dispatch is not None else default_dispatch,
            "dispatch_target": fn.dispatch_target,
        }
        for fn in spec.functions
    }

    lines: list[str] = []
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import argparse")
    lines.append("import os")
    lines.append("")
    lines.append("from devman_runtime import server as runtime_server")
    lines.append("")
    lines.append("RuntimeFunctionSpec = runtime_server.RuntimeFunctionSpec")
    lines.append("serve_manager = runtime_server.serve_manager")
    lines.append("")
    lines.append(f"FUNCTIONS = {pformat(function_map, indent=2, sort_dicts=True)}")
    lines.append("")
    lines.append("def _runtime_specs() -> dict[str, RuntimeFunctionSpec]:")
    lines.append("    return {")
    lines.append("        name: RuntimeFunctionSpec(")
    lines.append("            name=data['name'],")
    lines.append("            param_order=list(data['param_order']),")
    lines.append("            param_kinds=dict(data.get('param_kinds', {})),")
    lines.append("            resource_template=data['resource_template'],")
    lines.append("            dispatch=data.get('dispatch', 'default'),")
    lines.append("            dispatch_target=data.get('dispatch_target'),")
    lines.append("        )")
    lines.append("        for name, data in FUNCTIONS.items()")
    lines.append("    }")
    lines.append("")
    lines.append("def _parse_hook_args(raw_items: list[str]) -> dict[str, str]:")
    lines.append("    result: dict[str, str] = {}")
    lines.append("    for item in raw_items:")
    lines.append("        if '=' not in item:")
    lines.append("            raise ValueError(f\"invalid --hook-arg '{item}', expected key=value\")")
    lines.append("        key, value = item.split('=', 1)")
    lines.append("        key = key.strip()")
    lines.append("        if not key:")
    lines.append("            raise ValueError(f\"invalid --hook-arg '{item}', key cannot be empty\")")
    lines.append("        result[key] = value")
    lines.append("    return result")
    lines.append("")
    lines.append("def _env_flag(name: str, default: bool = False) -> bool:")
    lines.append("    raw = os.getenv(name)")
    lines.append("    if raw is None:")
    lines.append("        return default")
    lines.append("    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')")
    lines.append("")
    lines.append("def main() -> None:")
    lines.append("    parser = argparse.ArgumentParser(description='Run devman manager server')")
    lines.append("    parser.add_argument('--backend-module', default=os.getenv('DEVMAN_BACKEND_MODULE'), required=False)")
    lines.append("    parser.add_argument('--host', default=os.getenv('DEVMAN_HOST', '127.0.0.1'))")
    lines.append("    parser.add_argument('--port', type=int, default=int(os.getenv('DEVMAN_PORT', '50250')))")
    lines.append("    parser.add_argument('--db', default=os.getenv('DEVMAN_DB', './ownership.db'))")
    lines.append("    parser.add_argument('--verbose', action='store_true', default=_env_flag('DEVMAN_VERBOSE', False))")
    lines.append("    parser.add_argument('--init-function', default=os.getenv('DEVMAN_INIT_FUNCTION', ''))")
    lines.append("    parser.add_argument('--deinit-function', default=os.getenv('DEVMAN_DEINIT_FUNCTION', ''))")
    lines.append("    parser.add_argument('--init-file', default=os.getenv('DEVMAN_INIT_FILE', ''))")
    lines.append("    parser.add_argument('--deinit-file', default=os.getenv('DEVMAN_DEINIT_FILE', ''))")
    lines.append("    parser.add_argument('--init-file-function', default=os.getenv('DEVMAN_INIT_FILE_FUNCTION', 'init'))")
    lines.append("    parser.add_argument('--deinit-file-function', default=os.getenv('DEVMAN_DEINIT_FILE_FUNCTION', 'deinit'))")
    lines.append("    parser.add_argument('--singleton-function', default=os.getenv('DEVMAN_SINGLETON_FUNCTION', ''))")
    lines.append("    parser.add_argument('--singleton-file', default=os.getenv('DEVMAN_SINGLETON_FILE', ''))")
    lines.append("    parser.add_argument('--singleton-file-function', default=os.getenv('DEVMAN_SINGLETON_FILE_FUNCTION', 'get_singleton'))")
    lines.append("    parser.add_argument('--hook-arg', action='append', default=[], help='key=value pair passed to hooks (repeatable)')")
    lines.append("    parser.add_argument('--periodic-function', default=os.getenv('DEVMAN_PERIODIC_FUNCTION', ''))")
    lines.append("    parser.add_argument('--periodic-file', default=os.getenv('DEVMAN_PERIODIC_FILE', ''))")
    lines.append("    parser.add_argument('--periodic-file-function', default=os.getenv('DEVMAN_PERIODIC_FILE_FUNCTION', 'periodic'))")
    lines.append("    parser.add_argument('--periodic-interval-sec', type=float, default=float(os.getenv('DEVMAN_PERIODIC_INTERVAL_SEC', '0')))")
    lines.append("    parser.add_argument('--client-lease-sec', type=float, default=float(os.getenv('DEVMAN_CLIENT_LEASE_SEC', '90')), help='seconds without any request before a client counts as offline (0 = never); exposed to hooks via core.is_client_live')")
    lines.append("    args, extra_args = parser.parse_known_args()")
    lines.append("    if not args.backend_module:")
    lines.append("        parser.error('--backend-module or DEVMAN_BACKEND_MODULE is required')")
    lines.append("    if args.init_file and args.init_function:")
    lines.append("        parser.error('--init-file and --init-function are mutually exclusive')")
    lines.append("    if args.deinit_file and args.deinit_function:")
    lines.append("        parser.error('--deinit-file and --deinit-function are mutually exclusive')")
    lines.append("    if args.singleton_file and args.singleton_function:")
    lines.append("        parser.error('--singleton-file and --singleton-function are mutually exclusive')")
    lines.append("    if args.periodic_file and args.periodic_function:")
    lines.append("        parser.error('--periodic-file and --periodic-function are mutually exclusive')")
    lines.append("    try:")
    lines.append("        hook_options = _parse_hook_args(list(args.hook_arg))")
    lines.append("    except ValueError as exc:")
    lines.append("        parser.error(str(exc))")
    lines.append("    serve_manager(")
    lines.append("        backend_module=args.backend_module,")
    lines.append("        host=args.host,")
    lines.append("        port=args.port,")
    lines.append("        db_path=args.db,")
    lines.append("        functions=_runtime_specs(),")
    lines.append("        init_function=args.init_function or None,")
    lines.append("        deinit_function=args.deinit_function or None,")
    lines.append("        init_file=args.init_file or None,")
    lines.append("        deinit_file=args.deinit_file or None,")
    lines.append("        init_file_function=args.init_file_function,")
    lines.append("        deinit_file_function=args.deinit_file_function,")
    lines.append("        hook_args=hook_options,")
    lines.append("        extra_args=list(extra_args),")
    lines.append("        periodic_function=args.periodic_function or None,")
    lines.append("        periodic_file=args.periodic_file or None,")
    lines.append("        periodic_file_function=args.periodic_file_function,")
    lines.append("        periodic_interval_sec=float(args.periodic_interval_sec),")
    lines.append("        singleton_function=args.singleton_function or None,")
    lines.append("        singleton_file=args.singleton_file or None,")
    lines.append("        singleton_file_function=args.singleton_file_function,")
    lines.append("        verbose=bool(args.verbose),")
    lines.append("        client_lease_sec=float(args.client_lease_sec),")
    lines.append("    )")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    main()")
    lines.append("")
    return "\n".join(lines)


def _project_toml(project_name: str, module_name: str, script_target: str | None = None) -> str:
    lines = [
        "[build-system]",
        "requires = ['setuptools>=68', 'wheel']",
        "build-backend = 'setuptools.build_meta'",
        "",
        "[project]",
        f"name = '{project_name}'",
        "version = '0.1.0'",
        f"description = 'Generated devman package: {module_name}'",
        "readme = 'README.md'",
        "requires-python = '>=3.10'",
        "dependencies = ['devman-runtime>=0.1.0']",
        "",
    ]
    if script_target is not None:
        lines.extend(
            [
                "[project.scripts]",
                f"{module_name} = '{script_target}'",
                "",
            ]
        )

    lines.extend(
        [
            "[tool.setuptools]",
            'package-dir = {"" = "src"}',
            "",
            "[tool.setuptools.packages.find]",
            "where = ['src']",
            "",
        ]
    )
    return "\n".join(lines)


def _write_project_files(
    project_dir: Path, module_name: str, role: str, entry_script: str | None = None
) -> None:
    src_pkg = project_dir / "src" / module_name
    src_pkg.mkdir(parents=True, exist_ok=True)
    # Project metadata is scaffolded once and then owned by the repo:
    # regeneration must not clobber release metadata (version, license, urls).
    readme = project_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {module_name}\n\nGenerated by devman-gen. Runtime is provided by the devman-runtime package.\n",
            encoding="utf-8",
        )
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            _project_toml(project_name=project_dir.name, module_name=module_name, script_target=entry_script),
            encoding="utf-8",
        )


def _reset_project_dir(project_dir: Path) -> None:
    # Only the generated sources are reset; repo-owned files (pyproject,
    # README, LICENSE, .git*, workflows) are left untouched.
    src_dir = project_dir / "src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    project_dir.mkdir(parents=True, exist_ok=True)


def generate_bridge_packages(spec: BridgeSpec, output_dir: str | Path, package_name: str) -> dict[str, Path]:
    root = Path(output_dir)
    module_base = package_name.replace("-", "_")
    client_module = f"{module_base}_client"
    server_module = f"{module_base}_server"
    client_project_name = f"{package_name}-client"
    server_project_name = f"{package_name}-server"

    client_project = root / client_project_name
    server_project = root / server_project_name

    _reset_project_dir(client_project)
    _reset_project_dir(server_project)

    _write_project_files(client_project, module_name=client_module, role="client")
    _write_project_files(
        server_project,
        module_name=server_module,
        role="server",
        entry_script=f"{server_module}.server:main",
    )

    client_pkg = client_project / "src" / client_module
    server_pkg = server_project / "src" / server_module

    (client_pkg / "__init__.py").write_text(
        "from .client import *\n\n__all__ = [name for name in globals() if not name.startswith('_')]\n",
        encoding="utf-8",
    )
    (server_pkg / "__init__.py").write_text("", encoding="utf-8")

    (client_pkg / "client.py").write_text(_client_source(spec), encoding="utf-8")
    (server_pkg / "server.py").write_text(_server_source(spec), encoding="utf-8")

    spec_json = json.dumps(spec.to_dict(), indent=2) + "\n"
    (client_pkg / "spec.json").write_text(spec_json, encoding="utf-8")
    (server_pkg / "spec.json").write_text(spec_json, encoding="utf-8")

    return {"client": client_project, "server": server_project}
