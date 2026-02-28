from __future__ import annotations

import importlib
import socketserver
import traceback
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .db import OwnershipDB
from .protocol import recv_message, send_message


@dataclass(slots=True)
class RuntimeFunctionSpec:
    name: str
    param_order: list[str]
    param_kinds: dict[str, str]
    resource_template: str | None


class ManagerCore:
    def __init__(self, backend_module: str, db_path: str, functions: dict[str, RuntimeFunctionSpec]):
        self.backend = importlib.import_module(backend_module)
        self.db = OwnershipDB(db_path)
        self.functions = functions
        self._handles: dict[str, Any] = {}
        self._handles_lock = Lock()

    def _resolve_resources(
        self, fn_spec: RuntimeFunctionSpec, args: list[Any], kwargs: dict[str, Any]
    ) -> list[str]:
        if fn_spec.resource_template is None:
            return []

        context = dict(kwargs)
        positional_index = 0
        for name in fn_spec.param_order:
            kind = fn_spec.param_kinds.get(name, "POSITIONAL_OR_KEYWORD")
            if kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD") and positional_index < len(args):
                context.setdefault(name, args[positional_index])
                positional_index += 1

        try:
            return [fn_spec.resource_template.format(**context)]
        except Exception as exc:
            raise RuntimeError(f"failed to resolve resource template for {fn_spec.name}: {exc}") from exc

    def _resolve_dotted_callable(self, function: str) -> Any:
        target: Any = self.backend
        for token in function.split("."):
            target = getattr(target, token)
        if not callable(target):
            raise AttributeError(f"{function} is not callable")
        return target

    def _get_handle(self, handle: str) -> Any:
        with self._handles_lock:
            obj = self._handles.get(handle)
        if obj is None:
            raise RuntimeError(f"unknown handle: {handle}")
        return obj

    def _register_handle(self, obj: Any) -> str:
        handle = uuid.uuid4().hex
        with self._handles_lock:
            self._handles[handle] = obj
        return handle

    def _release_handle(self, handle: str) -> None:
        with self._handles_lock:
            self._handles.pop(handle, None)

    def _dispatch(self, function: str, args: list[Any], kwargs: dict[str, Any], handle: str | None) -> Any:
        if function == "Device_open":
            device_cls = getattr(self.backend, "Device")
            obj = device_cls.open(*args, **kwargs)
            return {"__devman_handle__": self._register_handle(obj)}

        if function.startswith("Device_"):
            method_name = function[len("Device_") :]
            if handle is not None:
                target = self._get_handle(handle)
            else:
                target = getattr(self.backend, "Device")
            method = getattr(target, method_name)
            result = method(*args, **kwargs)
            if method_name == "close" and handle is not None:
                self._release_handle(handle)
            return result

        backend_fn = self._resolve_dotted_callable(function)
        return backend_fn(*args, **kwargs)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        client = request.get("client")
        if not client:
            return {"status": "error", "error": "missing client name"}

        if op == "acquire":
            resource = request.get("resource")
            if not resource:
                return {"status": "error", "error": "missing resource"}
            return {"status": "ok", "acquired": self.db.acquire(str(resource), str(client))}

        if op == "release":
            resource = request.get("resource")
            if not resource:
                return {"status": "error", "error": "missing resource"}
            return {"status": "ok", "released": self.db.release(str(resource), str(client))}

        if op != "call":
            return {"status": "error", "error": f"unsupported operation: {op}"}

        function = request.get("function")
        if not function:
            return {"status": "error", "error": "missing function"}
        fn_spec = self.functions.get(str(function))
        if fn_spec is None:
            return {"status": "error", "error": f"unknown function: {function}"}

        args = request.get("args", [])
        kwargs = request.get("kwargs", {})
        handle = request.get("handle")
        resources = request.get("resources")
        if resources is None:
            resources = self._resolve_resources(fn_spec, list(args), dict(kwargs))

        for resource in resources:
            owner = self.db.owner_of(str(resource))
            if owner != client:
                return {
                    "status": "error",
                    "error": f"resource '{resource}' is owned by '{owner}'",
                }

        try:
            result = self._dispatch(str(function), list(args), dict(kwargs), handle=str(handle) if handle else None)
        except Exception:
            return {
                "status": "error",
                "error": f"backend call failed: {traceback.format_exc(limit=2)}",
            }
        return {"status": "ok", "result": result}


class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        assert isinstance(self.server, _ManagerTCPServer)
        request = recv_message(self.request)
        response = self.server.core.handle(request)
        send_message(self.request, response)


class _ManagerTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], core: ManagerCore):
        super().__init__(server_address, _TCPHandler)
        self.core = core


def serve_manager(
    backend_module: str,
    host: str,
    port: int,
    db_path: str,
    functions: dict[str, RuntimeFunctionSpec],
) -> None:
    core = ManagerCore(backend_module=backend_module, db_path=db_path, functions=functions)
    with _ManagerTCPServer((host, port), core) as server:
        server.serve_forever()
