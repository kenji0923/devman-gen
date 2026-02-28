from __future__ import annotations

import importlib
import inspect
import sys

from devman_gen.generator import generate_bridge_package
from devman_gen.runtime.server import ManagerCore, RuntimeFunctionSpec
from devman_gen.spec import BridgeFunctionSpec, BridgeSpec


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

        acquire = core.handle({"op": "acquire", "client": "alice", "resource": "channel:1"})
        assert acquire["status"] == "ok"
        assert acquire["acquired"] is True

        denied = core.handle(
            {
                "op": "call",
                "client": "bob",
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
        opened = core.handle(
            {
                "op": "call",
                "client": "alice",
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
