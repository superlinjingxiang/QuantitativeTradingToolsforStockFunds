"""Command-line entry point for foundation smoke checks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from china_quant_platform import __version__
from china_quant_platform.app.runtime import bootstrap_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="china-quant-platform",
        description="China Quant Platform foundation command.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0

    context = bootstrap_runtime(configure_logs=False)
    print(f"china_quant_platform {__version__}")
    print(f"project_root={context.project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
