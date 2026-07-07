"""Command line entry point for AFAC2026-4 Agent V0."""

from __future__ import annotations

import json
import sys

from .config import config_from_args, parse_args
from .runner import AgentRunner


def main() -> int:
    config = config_from_args(parse_args())
    try:
        runner = AgentRunner(config)
        summary = runner.run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
