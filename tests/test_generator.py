from __future__ import annotations

import importlib
import inspect
import os
import sys

from devman_gen.generator import generate_bridge_package
from devman_gen.introspect import build_spec_from_module
from devman_gen.runtime.client import ManagerClient
from devman_gen.runtime.server import (
    ManagerCore,
    RuntimeFunctionSpec,
    _invoke_hook,
    _resolve_file_callable,
    serve_manager,
)
from devman_gen.spec import BridgeFunctionSpec, BridgeSpec

os.environ.setdefault("DEVMAN_CLIENT", "test-client")


def _connect(core: ManagerCore, name: str) -> str:
    response = core.handle({"op": "connect", "client": name})
    assert response["status"] == "ok"
    return str(response["session"])


def test_manager_client_requires_name() -> None:
    try:
        ManagerClient(host="127.0.0.1", port=1, client_name="  ")
    except ValueError:
        return
    raise AssertionError("expected empty client_name to be rejected")


def test_resolve_file_callable_loads_hook(tmp_path) -> None:
    hook_file = tmp_path / "hooks.py"
    hook_file.write_text(
        "def init():\n"
        "    return 123\n",
        encoding="utf-8",
    )
    fn = _resolve_file_callable(str(hook_file), "init")
    assert fn() == 123


def test_invoke_hook_passes_context_kwargs() -> None:
    captured: dict[str, object] = {}

    def hook(hook_args, extra_args, backend_module):
        captured["hook_args"] = hook_args
        captured["extra_args"] = extra_args
        captured["backend_module"] = backend_module

    _invoke_hook(
        hook,
        {
            "hook_args": {"device_ip": "1.2.3.4", "username": "u"},
            "extra_args": ["--crate-ip", "1.2.3.4"],
            "backend_module": "some.backend",
            "port": 123,
        },
    )
    assert captured["hook_args"] == {"device_ip": "1.2.3.4", "username": "u"}
    assert captured["extra_args"] == ["--crate-ip", "1.2.3.4"]
    assert captured["backend_module"] == "some.backend"


def test_serve_manager_rejects_mixed_hook_sources() -> None:
    try:
        serve_manager(
            backend_module="unused.backend",
            host="127.0.0.1",
            port=0,
            db_path=":memory:",
            functions={},
            init_function="x.y",
            init_file="/tmp/init.py",
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
        return
    raise AssertionError("expected serve_manager to reject mixed init hook sources")


def test_generated_client_preserves_signature_and_packaging(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        functions=[
            BridgeFunctionSpec(
                name="configure",
                signature="(channel, voltage=0.0, *, ramp=False, **kwargs)",
                param_order=["channel", "voltage", "ramp", "kwargs"],
                param_kinds={
                    "channel": "POSITIONAL_OR_KEYWORD",
                    "voltage": "POSITIONAL_OR_KEYWORD",
                    "ramp": "KEYWORD_ONLY",
                    "kwargs": "VAR_KEYWORD",
                },
                resource_template="channel:{channel}",
            )
        ],
    )

    package_root = tmp_path / "out"
    package_name = "generated_bridge"
    generate_bridge_package(spec, package_root, package_name)

    sys.path.insert(0, str(package_root))
    try:
        client = importlib.import_module(f"{package_name}.client")
        assert str(inspect.signature(client.configure)) == "(channel, voltage=0.0, *, ramp=False, **kwargs)"

        captured: dict[str, object] = {}

        class FakeClient:
            def invoke(self, function, args, kwargs, resources):
                captured["function"] = function
                captured["args"] = args
                captured["kwargs"] = kwargs
                captured["resources"] = resources
                return "ok"

            def acquire(self, resource):
                return True

            def release(self, resource):
                return True

        client._CLIENT = FakeClient()
        result = client.configure(2, ramp=True, mode="safe")

        assert result == "ok"
        assert captured["function"] == "configure"
        assert captured["args"] == [2, 0.0]
        assert captured["kwargs"] == {"ramp": True, "mode": "safe"}
        assert captured["resources"] == ["channel:2"]
    finally:
        sys.path.pop(0)


def test_generated_server_supports_arbitrary_hook_args(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        functions=[
            BridgeFunctionSpec(
                name="ping",
                signature="()",
                param_order=[],
                param_kinds={},
                resource_template=None,
            )
        ],
    )
    package_root = tmp_path / "out"
    package_name = "generated_bridge_server_args"
    generate_bridge_package(spec, package_root, package_name)

    server_text = (package_root / package_name / "server.py").read_text(encoding="utf-8")
    assert "parse_known_args" in server_text
    assert "--hook-arg" in server_text
    assert "hook_args=hook_options" in server_text
    assert "extra_args=list(extra_args)" in server_text
    assert "--verbose" in server_text
    assert "verbose=bool(args.verbose)" in server_text
    assert "--singleton-function" in server_text
    assert "--singleton-file" in server_text
    assert "--singleton-file-function" in server_text
    assert "--username" not in server_text
    assert "--password" not in server_text


def test_default_dispatch_applies_when_function_dispatch_omitted(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        default_dispatch="singleton",
        functions=[
            BridgeFunctionSpec(
                name="ping",
                signature="()",
                param_order=[],
                param_kinds={},
                resource_template=None,
                dispatch=None,
            )
        ],
    )
    package_root = tmp_path / "out"
    package_name = "generated_bridge_default_dispatch"
    generate_bridge_package(spec, package_root, package_name)
    server_text = (package_root / package_name / "server.py").read_text(encoding="utf-8")
    assert "'dispatch': 'singleton'" in server_text


def test_generated_client_supports_none_templates(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        functions=[
            BridgeFunctionSpec(
                name="ping",
                signature="()",
                param_order=[],
                param_kinds={},
                resource_template=None,
            )
        ],
    )

    package_root = tmp_path / "out"
    package_name = "generated_bridge_none"
    generate_bridge_package(spec, package_root, package_name)

    sys.path.insert(0, str(package_root))
    try:
        client = importlib.import_module(f"{package_name}.client")
        assert hasattr(client, "ping")
    finally:
        sys.path.pop(0)


def test_generated_package_vendors_runtime(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        functions=[
            BridgeFunctionSpec(
                name="ping",
                signature="()",
                param_order=[],
                param_kinds={},
                resource_template=None,
            )
        ],
    )
    package_root = tmp_path / "out"
    package_name = "generated_bridge_runtime"
    package_dir = generate_bridge_package(spec, package_root, package_name)

    client_text = (package_dir / "client.py").read_text(encoding="utf-8")
    server_text = (package_dir / "server.py").read_text(encoding="utf-8")
    assert "from .runtime.client import ManagerClient" in client_text
    assert "from .runtime import server as runtime_server" in server_text
    assert (package_dir / "runtime" / "__init__.py").exists()
    assert (package_dir / "runtime" / "client.py").exists()
    assert (package_dir / "runtime" / "server.py").exists()


def test_generated_client_expands_list_placeholders_in_resource_template(tmp_path) -> None:
    spec = BridgeSpec(
        module="backend_mod",
        functions=[
            BridgeFunctionSpec(
                name="set_channels",
                signature="(slot, channel_list, value)",
                param_order=["slot", "channel_list", "value"],
                param_kinds={
                    "slot": "POSITIONAL_OR_KEYWORD",
                    "channel_list": "POSITIONAL_OR_KEYWORD",
                    "value": "POSITIONAL_OR_KEYWORD",
                },
                resource_template="slot:{slot}:ch:{channel_list[]}",
            )
        ],
    )

    package_root = tmp_path / "out"
    package_name = "generated_bridge_expand_lock"
    generate_bridge_package(spec, package_root, package_name)

    sys.path.insert(0, str(package_root))
    try:
        client = importlib.import_module(f"{package_name}.client")
        captured: dict[str, object] = {}

        class FakeClient:
            def invoke(self, function, args, kwargs, resources):
                captured["function"] = function
                captured["args"] = args
                captured["kwargs"] = kwargs
                captured["resources"] = resources
                return "ok"

            def acquire(self, resource):
                return True

            def release(self, resource):
                return True

        client._CLIENT = FakeClient()
        result = client.set_channels(2, [3, 7], 10.0)

        assert result == "ok"
        assert captured["function"] == "set_channels"
        assert captured["resources"] == ["slot:2:ch:3", "slot:2:ch:7"]
    finally:
        sys.path.pop(0)


def test_introspect_captures_referenced_external_types(tmp_path) -> None:
    ext_types_file = tmp_path / "ext_types.py"
    ext_types_file.write_text(
        "from enum import IntEnum\n"
        "class SystemType(IntEnum):\n"
        "    A = 1\n"
        "class LinkType(IntEnum):\n"
        "    ETH = 0\n"
        "class Payload:\n"
        "    pass\n",
        encoding="utf-8",
    )
    backend_file = tmp_path / "fake_backend_types.py"
    backend_file.write_text(
        "import ext_types\n"
        "class Device:\n"
        "    @classmethod\n"
        "    def open(cls, system_type: ext_types.SystemType, link_type: ext_types.LinkType, payload: ext_types.Payload):\n"
        "        return cls()\n",
        encoding="utf-8",
    )

    package_root = tmp_path / "out"
    sys.path.insert(0, str(tmp_path))
    try:
        spec = build_spec_from_module("fake_backend_types")
        assert "ext_types" in spec.extra_imports
        assert spec.captured_types["SystemType"]["type"] == "IntEnum"
        assert spec.captured_types["SystemType"]["members"] == {"A": 1}
        assert spec.captured_types["Payload"]["type"] == "Class"

        package_name = "generated_bridge_types"
        generate_bridge_package(spec, package_root, package_name)

        sys.path.pop(0)
        sys.path.insert(0, str(package_root))
        client = importlib.import_module(f"{package_name}.client")
        assert client.SystemType.A.name == "A"
        assert hasattr(client, "Payload")
    finally:
        if str(package_root) in sys.path:
            sys.path.remove(str(package_root))
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))


def test_manager_core_enforces_ownership(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend.py"
    backend_file.write_text(
        "def set_voltage(channel, value):\n"
        "    return {'channel': channel, 'value': value}\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))

    try:
        functions = {
            "set_voltage": RuntimeFunctionSpec(
                name="set_voltage",
                param_order=["channel", "value"],
                param_kinds={
                    "channel": "POSITIONAL_OR_KEYWORD",
                    "value": "POSITIONAL_OR_KEYWORD",
                },
                resource_template="channel:{channel}",
            )
        }
        core = ManagerCore(
            backend_module="fake_backend",
            db_path=str(tmp_path / "ownership.db"),
            functions=functions,
        )
        alice_session = _connect(core, "alice")
        bob_session = _connect(core, "bob")

        acquire = core.handle(
            {"op": "acquire", "client": "alice", "session": alice_session, "resource": "channel:1"}
        )
        assert acquire["status"] == "ok"
        assert acquire["acquired"] is True

        denied = core.handle(
            {
                "op": "call",
                "client": "bob",
                "session": bob_session,
                "function": "set_voltage",
                "args": [1, 10.0],
                "kwargs": {},
                "resources": ["channel:1"],
            }
        )
        assert denied["status"] == "error"

        ok = core.handle(
            {
                "op": "call",
                "client": "alice",
                "session": alice_session,
                "function": "set_voltage",
                "args": [1, 10.0],
                "kwargs": {},
                "resources": ["channel:1"],
            }
        )
        assert ok["status"] == "ok"
        assert ok["result"] == {"channel": 1, "value": 10.0}
    finally:
        sys.path.pop(0)


def test_manager_core_expands_list_resource_template_when_resources_omitted(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_expand.py"
    backend_file.write_text(
        "def set_many(channel_list, value):\n"
        "    return {'channels': list(channel_list), 'value': value}\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        functions = {
            "set_many": RuntimeFunctionSpec(
                name="set_many",
                param_order=["channel_list", "value"],
                param_kinds={
                    "channel_list": "POSITIONAL_OR_KEYWORD",
                    "value": "POSITIONAL_OR_KEYWORD",
                },
                resource_template="ch:{channel_list[]}",
            )
        }
        core = ManagerCore(
            backend_module="fake_backend_expand",
            db_path=str(tmp_path / "ownership.db"),
            functions=functions,
        )
        alice_session = _connect(core, "alice")

        assert core.handle(
            {"op": "acquire", "client": "alice", "session": alice_session, "resource": "ch:1"}
        )["acquired"] is True
        assert core.handle(
            {"op": "acquire", "client": "alice", "session": alice_session, "resource": "ch:2"}
        )["acquired"] is True

        ok = core.handle(
            {
                "op": "call",
                "client": "alice",
                "session": alice_session,
                "function": "set_many",
                "args": [[1, 2], 5.0],
                "kwargs": {},
            }
        )
        assert ok["status"] == "ok"
        assert ok["result"] == {"channels": [1, 2], "value": 5.0}
    finally:
        sys.path.pop(0)


def test_manager_core_device_handle_dispatch(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_dev.py"
    backend_file.write_text(
        "class Device:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "    @classmethod\n"
        "    def open(cls, value):\n"
        "        return cls(value)\n"
        "    def get_value(self):\n"
        "        return self.value\n"
        "    def close(self):\n"
        "        return None\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        functions = {
            "Device_open": RuntimeFunctionSpec(
                name="Device_open",
                param_order=["value"],
                param_kinds={"value": "POSITIONAL_OR_KEYWORD"},
                resource_template=None,
            ),
            "Device_get_value": RuntimeFunctionSpec(
                name="Device_get_value",
                param_order=[],
                param_kinds={},
                resource_template=None,
            ),
            "Device_close": RuntimeFunctionSpec(
                name="Device_close",
                param_order=[],
                param_kinds={},
                resource_template=None,
            ),
        }
        core = ManagerCore(
            backend_module="fake_backend_dev",
            db_path=str(tmp_path / "ownership.db"),
            functions=functions,
        )
        alice_session = _connect(core, "alice")
        opened = core.handle(
            {
                "op": "call",
                "client": "alice",
                "session": alice_session,
                "function": "Device_open",
                "args": [7],
                "kwargs": {},
                "resources": [],
            }
        )
        assert opened["status"] == "ok"
        handle = opened["result"]["__devman_handle__"]

        value = core.handle(
            {
                "op": "call",
                "client": "alice",
                "session": alice_session,
                "function": "Device_get_value",
                "args": [],
                "kwargs": {},
                "resources": [],
                "handle": handle,
            }
        )
        assert value["status"] == "ok"
        assert value["result"] == 7
    finally:
        sys.path.pop(0)


def test_manager_core_singleton_dispatch(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_singleton.py"
    backend_file.write_text(
        "class Box:\n"
        "    def value(self):\n"
        "        return 42\n"
        "def make_box():\n"
        "    return Box()\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        mod = importlib.import_module("fake_backend_singleton")
        core = ManagerCore(
            backend_module="fake_backend_singleton",
            db_path=str(tmp_path / "ownership.db"),
            functions={
                "Device_value": RuntimeFunctionSpec(
                    name="Device_value",
                    param_order=[],
                    param_kinds={},
                    resource_template=None,
                    dispatch="singleton",
                    dispatch_target="value",
                )
            },
            singleton_object=mod.make_box(),
        )
        session = _connect(core, "alice")
        result = core.handle(
            {
                "op": "call",
                "client": "alice",
                "session": session,
                "function": "Device_value",
                "args": [],
                "kwargs": {},
                "resources": [],
            }
        )
        assert result["status"] == "ok"
        assert result["result"] == 42
    finally:
        sys.path.pop(0)


def test_manager_core_rejects_duplicate_client_names(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_dup.py"
    backend_file.write_text("def ping():\n    return 'ok'\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        core = ManagerCore(
            backend_module="fake_backend_dup",
            db_path=str(tmp_path / "ownership.db"),
            functions={
                "ping": RuntimeFunctionSpec(
                    name="ping",
                    param_order=[],
                    param_kinds={},
                    resource_template=None,
                )
            },
        )
        first = core.handle({"op": "connect", "client": "same"})
        assert first["status"] == "ok"

        duplicate = core.handle({"op": "connect", "client": "same"})
        assert duplicate["status"] == "error"
        assert "already connected" in str(duplicate["error"])
    finally:
        sys.path.pop(0)


def test_manager_core_force_connect_replaces_existing_session(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_force.py"
    backend_file.write_text("def ping():\n    return 'ok'\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        core = ManagerCore(
            backend_module="fake_backend_force",
            db_path=str(tmp_path / "ownership.db"),
            functions={
                "ping": RuntimeFunctionSpec(
                    name="ping",
                    param_order=[],
                    param_kinds={},
                    resource_template=None,
                )
            },
        )
        first = core.handle({"op": "connect", "client": "same"})
        assert first["status"] == "ok"
        first_session = str(first["session"])
        assert core.handle(
            {"op": "acquire", "client": "same", "session": first_session, "resource": "r:1"}
        )["acquired"] is True

        forced = core.handle({"op": "connect", "client": "same", "force": True})
        assert forced["status"] == "ok"
        second_session = str(forced["session"])
        assert second_session != first_session

        old_session_denied = core.handle(
            {"op": "call", "client": "same", "session": first_session, "function": "ping", "args": [], "kwargs": {}}
        )
        assert old_session_denied["status"] == "error"

        # Force-connect keeps existing ownership for that client identity.
        assert core.db.owner_of("r:1") == "same"
        ok = core.handle(
            {"op": "call", "client": "same", "session": second_session, "function": "ping", "args": [], "kwargs": {}}
        )
        assert ok["status"] == "ok"
        assert ok["result"] == "ok"
    finally:
        sys.path.pop(0)


def test_disconnect_keeps_owned_resources(tmp_path) -> None:
    backend_file = tmp_path / "fake_backend_disc.py"
    backend_file.write_text("def ping():\n    return 'ok'\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        core = ManagerCore(
            backend_module="fake_backend_disc",
            db_path=str(tmp_path / "ownership.db"),
            functions={
                "ping": RuntimeFunctionSpec(
                    name="ping",
                    param_order=[],
                    param_kinds={},
                    resource_template=None,
                )
            },
        )
        first = core.handle({"op": "connect", "client": "same"})
        assert first["status"] == "ok"
        first_session = str(first["session"])
        assert core.handle(
            {"op": "acquire", "client": "same", "session": first_session, "resource": "r:1"}
        )["acquired"] is True

        disc = core.handle({"op": "disconnect", "client": "same", "session": first_session})
        assert disc["status"] == "ok"
        assert core.db.owner_of("r:1") == "same"
    finally:
        sys.path.pop(0)
