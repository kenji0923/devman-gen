# devman-gen

`devman-gen` generates a managed client/server bridge for Python hardware-control libraries.

## What it provides

- Client wrapper module with the same Python function signatures as the original library.
- Manager server that validates resource ownership before calling the real backend library.
- SQLite-backed ownership tracking (`acquire` / `release`).
- Generator CLI that can build from live module introspection or a JSON spec.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Create a spec from an installed module
devman-gen introspect --module some_library --output spec.json

# Generate a bridge package
devman-gen generate --spec spec.json --output ./generated_bridge --package-name my_bridge
```

Use generated package:

```python
from my_bridge.client import configure, acquire, release

acquire("channel:0")
configure(0, voltage=100.0)
release("channel:0")
```

Start manager:

```bash
python -m my_bridge.server --backend-module some_library --host 127.0.0.1 --port 50250 --db ./ownership.db
```

## Spec format

`devman-gen introspect` emits JSON with:

- `module`: backend import path
- `functions[]`:
  - `name`
  - `signature` (Python signature text)
  - `param_order` (ordered parameter names)
  - `resource_template` (optional, default uses first argument)

`resource_template` uses Python `str.format` variables from call arguments.
Example: `"channel:{channel}"`.
