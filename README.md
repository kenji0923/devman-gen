# devman-gen

`devman-gen` generates managed client/server bridge packages for Python hardware-control libraries.

## What it provides

- Client wrapper module with the same Python function signatures as the original library.
- Manager server that validates resource ownership before calling the real backend library.
- SQLite-backed ownership tracking (`acquire` / `release`).
- Client/server session handshake with duplicate-name protection.
- Generator CLI that can build from live module introspection or a JSON spec.
- Split standalone output: separate installable client and server packages.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Create a spec from an installed module
devman-gen introspect --module some_library --output spec.json

# Generate split bridge packages
devman-gen generate --spec spec.json --output ./generated_bridge --package-name my-bridge
# output:
#   generated_bridge/my-bridge-client
#   generated_bridge/my-bridge-server
```

Install client machine:

```bash
pip install ./generated_bridge/my-bridge-client
```

Install server machine:

```bash
pip install ./generated_bridge/my-bridge-server
```

Use generated client package:

```python
import os
from my_bridge_client.client import configure, connect, disconnect, acquire, release

os.environ["DEVMAN_CLIENT"] = "alice"  # required
connect()
acquire("channel:0")
configure(0, voltage=100.0)
release("channel:0")
disconnect()
```

Start manager from server package:

```bash
python -m my_bridge_server.server --backend-module some_library --host 127.0.0.1 --port 50250 --db ./ownership.db
# or script entrypoint (same args):
# my_bridge_server --backend-module some_library ...
```

## Session and client identity

- Client name is required (`DEVMAN_CLIENT` or `configure_connection(..., client_name=...)`).
- Each client must `connect()` before use. Runtime auto-connects on first call, but explicit `connect()` is recommended.
- Duplicate names are rejected by default.
- Use `connect(force=True)` to take over an existing same-name session.
  - This evicts only the old session state for that name.
- `disconnect()` removes only the active session.
- Resource ownership is not auto-cleaned on `disconnect()` or forced reconnect.

## Server init/deinit hooks

You can run startup/shutdown logic in either of two ways:

- Dotted backend callables:
  - `--init-function backend.path.to_init`
  - `--deinit-function backend.path.to_deinit`
- Python hook files:
  - `--init-file /path/hooks.py --init-file-function init`
  - `--deinit-file /path/hooks.py --deinit-file-function deinit`
- Singleton provider callables:
  - `--singleton-function backend.path.to_get_singleton`
  - `--singleton-file /path/hooks.py --singleton-file-function get_singleton`

Server accepts arbitrary extra CLI arguments (`parse_known_args`) and passes them to hooks as `extra_args`.
You can also pass structured key-value pairs with repeatable `--hook-arg key=value`, available in hooks as `hook_args`.
If no explicit singleton provider is configured, the return value of `init` is used as the singleton object (when non-`None`).

Example:

```bash
python -m my_bridge_server.server \
  --backend-module some_library \
  --init-file ./hooks.py \
  --deinit-file ./hooks.py \
  --hook-arg device_ip=192.168.1.100 \
  --hook-arg username=admin \
  --hook-arg password=secret \
  --crate-port 1234
```

In hook functions, consume:

- `hook_args` for `key=value` pairs
- `extra_args` for arbitrary pass-through CLI tokens

Equivalent environment variables:

- `DEVMAN_INIT_FUNCTION`, `DEVMAN_DEINIT_FUNCTION`
- `DEVMAN_INIT_FILE`, `DEVMAN_DEINIT_FILE`
- `DEVMAN_INIT_FILE_FUNCTION`, `DEVMAN_DEINIT_FILE_FUNCTION`
- `DEVMAN_SINGLETON_FUNCTION`
- `DEVMAN_SINGLETON_FILE`
- `DEVMAN_SINGLETON_FILE_FUNCTION`

`--init-file` and `--init-function` are mutually exclusive (same for deinit).
`--singleton-file` and `--singleton-function` are mutually exclusive.

## Spec format

`devman-gen introspect` emits JSON with:

- `module`: backend import path
- `functions[]`:
  - `name`
  - `signature` (Python signature text)
  - `param_order` (ordered parameter names)
  - `param_kinds`
  - `resource_template` (optional, default uses first argument)
  - `dispatch` (optional override)
  - `dispatch_target` (optional target name for non-default dispatchers)

- `default_dispatch` (spec-level default applied to all functions unless overridden by function `dispatch`)

`resource_template` uses Python `str.format` variables from call arguments.
Example: `"channel:{channel}"`.

Dispatch notes:

- Use `default_dispatch` for the common case.
- Set function `dispatch` only where behavior differs from `default_dispatch`.
- For singleton dispatch, function names are not rewritten implicitly; set `dispatch_target` when needed.

List expansion is supported with `[]`:

- Template: `"slot:{slot}:ch:{channel_list[]}"`
- Args: `slot=2`, `channel_list=[3, 7]`
- Resources: `["slot:2:ch:3", "slot:2:ch:7"]`
