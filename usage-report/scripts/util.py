"""Shared helpers for the usage-report skill."""

import os
import sys
from pathlib import Path


def find_workspace() -> Path:
    """Resolve the OpenClaw workspace directory.

    Order of resolution:
      1. $OPENCLAW_WORKSPACE (explicit override)
      2. ~/.openclaw/workspace*  (alphabetically first; warns if multiple)

    Exits with a clear message if none exist — silently creating a
    throwaway workspace tends to hide misconfigured installs.
    """
    env = os.environ.get("OPENCLAW_WORKSPACE")
    if env:
        return Path(env)

    base = Path.home() / ".openclaw"
    if base.is_dir():
        candidates = sorted(
            p for p in base.iterdir()
            if p.is_dir() and p.name.startswith("workspace")
        )
        if len(candidates) > 1:
            print(
                f"  ⚠ Multiple workspaces found, using {candidates[0].name}. "
                f"Set OPENCLAW_WORKSPACE to override.",
                file=sys.stderr,
            )
        if candidates:
            return candidates[0]

    sys.exit(
        "No OpenClaw workspace found. "
        "Set $OPENCLAW_WORKSPACE or create ~/.openclaw/workspace*."
    )
