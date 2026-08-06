from __future__ import annotations

import argparse
from pathlib import Path

from .config import RuntimePaths


def main() -> int:
    parser = argparse.ArgumentParser(description="Mini-Hyra local research harness")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="runtime root")
    parser.add_argument("command", choices=["init"], nargs="?", default="init")
    args = parser.parse_args()
    paths = RuntimePaths.from_root(args.root)
    paths.ensure()
    print(f"Initialized Mini-Hyra runtime at {paths.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
