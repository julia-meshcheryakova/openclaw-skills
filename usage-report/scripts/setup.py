#!/usr/bin/env python3
"""
setup.py — Initial setup and backfill for the usage-report skill.

Run once to initialise directory structure, copy default config and category
map, then optionally backfill all historical session data.

Usage:
    python3 scripts/setup.py             # setup only (no backfill)
    python3 scripts/setup.py --backfill  # setup + extract + label all history
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


from util import find_workspace


SKILL_DIR = Path(__file__).parent.parent
WORKSPACE = find_workspace()

DIRS = [
    WORKSPACE / "data" / "usage" / "extracted",
    WORKSPACE / "data" / "usage" / "labeled",
    WORKSPACE / "data" / "usage" / "raw",
    WORKSPACE / "exports" / "weekly",
    WORKSPACE / "exports" / "alltime",
]

CAT_MAP_SRC  = SKILL_DIR / "assets" / "category-map.json"
CAT_MAP_DEST = WORKSPACE / "data" / "usage" / "category-map.json"
CONFIG_DEST  = WORKSPACE / "data" / "usage" / "config.json"

DEFAULT_CONFIG = {
    "provider": "copilot",
    "model": "claude-sonnet-4",
    "apiKey": "$GITHUB_TOKEN",
    "baseUrl": "https://api.githubcopilot.com",
    "_comment": "Supported providers: copilot, openai, anthropic. All use OpenAI-compatible chat format. apiKey supports $ENV_VAR syntax."
}


def create_dirs():
    print("Creating directory structure...")
    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {d.relative_to(Path.home())}")


def copy_category_map():
    if CAT_MAP_DEST.exists():
        print(f"\nCategory map already exists at {CAT_MAP_DEST.relative_to(Path.home())} — skipping.")
        return
    shutil.copy(CAT_MAP_SRC, CAT_MAP_DEST)
    print(f"\nCopied default category map → {CAT_MAP_DEST.relative_to(Path.home())}")
    print("  Edit this file to add your own subcategories under each category.")


def create_config():
    if CONFIG_DEST.exists():
        print(f"Config already exists at {CONFIG_DEST.relative_to(Path.home())} — skipping.")
        return
    with open(CONFIG_DEST, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    print(f"\nCreated default config → {CONFIG_DEST.relative_to(Path.home())}")
    print("  Edit this file to set your LLM provider and API key.")


def run_backfill():
    print("\n" + "─" * 60)
    print("Running backfill: extract all historical session data...")
    scripts_dir = SKILL_DIR / "scripts"

    result = subprocess.run(
        [sys.executable, str(scripts_dir / "extract-usage.py"), "--all"],
        env={**os.environ, "OPENCLAW_WORKSPACE": str(WORKSPACE)},
    )
    if result.returncode != 0:
        print("  ⚠ extract-usage.py exited with errors. Check output above.")

    print("\n" + "─" * 60)
    print("Running backfill: label all extracted dates...")
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "label-usage.py"), "--all"],
        env={**os.environ, "OPENCLAW_WORKSPACE": str(WORKSPACE)},
    )
    if result.returncode != 0:
        print("  ⚠ label-usage.py exited with errors. Check output above.")


def main():
    print(f"Usage-report setup")
    print(f"Workspace: {WORKSPACE}")
    print("─" * 60)

    create_dirs()
    copy_category_map()
    create_config()

    backfill = "--backfill" in sys.argv[1:]

    print("\n" + "─" * 60)
    if backfill:
        run_backfill()
    else:
        print("Setup complete.")
        print("\nNext steps:")
        print(f"  1. Edit {CAT_MAP_DEST.relative_to(Path.home())} — customise your categories")
        print(f"  2. Edit {CONFIG_DEST.relative_to(Path.home())} — set your LLM provider/key")
        print(f"  3. Run backfill:  python3 scripts/setup.py --backfill")
        print(f"  4. Weekly report: python3 scripts/weekly-report.py")


if __name__ == "__main__":
    main()
