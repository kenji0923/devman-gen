from __future__ import annotations

import socket
from typing import Any

from .protocol import recv_message, send_message


class ManagerError(RuntimeError):
    pass


class ManagerClient:
    def __init__(
        self,
        host: str,
        port: int,
        client_name: str,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.client_name = client_name
        self.timeout = timeout

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            send_message(sock, payload)
            response = recv_message(sock)

        if response.get("status") != "ok":
            error = response.get("error", "unknown manager error")
            raise ManagerError(str(error))
        return response

    def acquire(self, resource: str) -> bool:
        response = self._request(
            {
                "op": "acquire",
                "client": self.client_name,
                "resource": resource,
            }
        )
        return bool(response.get("acquired", False))

    def release(self, resource: str) -> bool:
        response = self._request(
            {
                "op": "release",
                "client": self.client_name,
                "resource": resource,
            }
        )
        return bool(response.get("released", False))

    def invoke(
        self,
        function: str,
        args: list[Any],
        kwargs: dict[str, Any],
        resources: list[str],
        handle: str | None = None,
    ) -> Any:
        payload = {
            "op": "call",
            "client": self.client_name,
            "function": function,
            "args": args,
            "kwargs": kwargs,
            "resources": resources,
        }
        if handle is not None:
            payload["handle"] = handle
        response = self._request(payload)
        return response.get("result")
