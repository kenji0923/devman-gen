from __future__ import annotations

import argparse
import sys

from .generator import generate_bridge_package
from .introspect import build_spec_from_module
from .spec import BridgeSpec


def _cmd_introspect(args: argparse.Namespace) -> int:
    spec = build_spec_from_module(args.module)
    spec.write_json(args.output)
    print(f"wrote spec for {args.module} to {args.output}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    spec = BridgeSpec.read_json(args.spec)
    package_dir = generate_bridge_package(spec=spec, output_dir=args.output, package_name=args.package_name)
    print(f"generated bridge package at {package_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate managed bridge packages")
    sub = parser.add_subparsers(dest="cmd", required=True)

    introspect = sub.add_parser("introspect", help="build function spec from importable module")
    introspect.add_argument("--module", required=True, help="Python module import path")
    introspect.add_argument("--output", required=True, help="Output JSON spec path")
    introspect.set_defaults(func=_cmd_introspect)

    generate = sub.add_parser("generate", help="generate bridge package from spec")
    generate.add_argument("--spec", required=True, help="Input JSON spec path")
    generate.add_argument("--output", required=True, help="Output directory")
    generate.add_argument("--package-name", required=True, help="Generated Python package name")
    generate.set_defaults(func=_cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
