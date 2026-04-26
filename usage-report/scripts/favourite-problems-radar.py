#!/usr/bin/env python3
"""Generate Favourite Problems Radar from labeled usage data.

Reads problems from knowledge/favourite-problems.md (or falls back to defaults).
Maps usage categories to problems via configurable mapping.
"""
import json, os, re, sys
from pathlib import Path
from collections import defaultdict
from math import pi

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", Path.home() / ".openclaw" / "workspace"))
ANALYZED_DIR = WORKSPACE / "data" / "usage" / "analyzed"
LABELED_DIR = WORKSPACE / "data" / "usage" / "labeled"  # fallback
PROBLEMS_FILE = WORKSPACE / "knowledge" / "favourite-problems.md"
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/favourite-problems-radar.png")


def load_problems() -> list:
    """Read problems from favourite-problems.md, or use generic defaults."""
    if PROBLEMS_FILE.exists():
        content = PROBLEMS_FILE.read_text(encoding="utf-8")
        # Parse numbered problems: "1. **How do I ...?**"
        problems = re.findall(r'\d+\.\s+\*\*(.+?)\*\*', content)
        # Shorten for chart labels (first 3-4 words)
        short = []
        for p in problems:
            words = p.replace("How do I ", "").replace("?", "").strip().split()
            label = " ".join(words[:3])
            if len(label) > 20:
                label = label[:18] + "..."
            short.append(label)
        return short if short else _defaults()
    return _defaults()


def _defaults() -> list:
    """Generic defaults for distribution."""
    return [
        "Automation",
        "Learning",
        "Family",
        "Finance",
        "Health",
        "Relationships",
        "Work Impact",
    ]


# Category → problem index mapping (configurable)
# Maps Julia's usage categories to favourite problem indices
CAT_TO_PROBLEM_IDX = {
    "config": 0, "side-projects": 0,          # → first problem (automation/productivity)
    "learning": 1, "creative": 1,              # → second problem (learning/intellectual)
    "family": 2,                               # → third problem (family/children)
    "finance": 3,                              # → fourth problem (finance)
    "health": 4, "health/sport": 4,            # → fifth problem (health)
    "social": 5, "personal": 5,                # → sixth problem (relationships)
    "work": 6,                                 # → seventh problem (work)
    "entertainment": 1,                        # → learning/intellectual
}


def main():
    problems = load_problems()
    N = len(problems)

    # Load all labeled data
    problem_minutes = defaultdict(float)
    total_minutes = 0
    seen_dates = set()

    # Try new analyzed format first, fall back to old labeled
    for source_dir in [ANALYZED_DIR, LABELED_DIR]:
        for f in sorted(source_dir.glob("*.json")):
            if f.stem in seen_dates:
                continue
            seen_dates.add(f.stem)
            with open(f) as fh:
                data = json.load(fh)
            # New format: categories as percentages
            if "categories" in data:
                for cat, pct in data["categories"].items():
                    idx = CAT_TO_PROBLEM_IDX.get(cat, 0)
                    if idx < N:
                        problem_minutes[idx] += pct
                    total_minutes += pct
            # Old format: category_minutes
            elif "category_minutes" in data:
                for cat, mins in data["category_minutes"].items():
                    idx = CAT_TO_PROBLEM_IDX.get(cat, 0)
                    if idx < N:
                        problem_minutes[idx] += mins
                    total_minutes += mins

    if total_minutes == 0:
        print("No labeled data found")
        sys.exit(0)

    values = [problem_minutes.get(i, 0) / total_minutes for i in range(N)]

    # Balanced target
    ideal = [1.0 / N] * N

    # Radar chart
    angles = [n / float(N) * 2 * pi for n in range(N)]
    angles += angles[:1]
    values += values[:1]
    ideal += ideal[:1]

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor('#0f0f1a')
    ax.set_facecolor('#161625')

    ax.plot(angles, values, 'o-', linewidth=2.5, color='#00d4aa',
            label=f'Actual ({round(total_minutes/60, 1)}h)', markersize=8)
    ax.fill(angles, values, alpha=0.15, color='#00d4aa')
    ax.plot(angles, ideal, 'o--', linewidth=1.5, color='#e94560',
            label='Balanced target', markersize=6, alpha=0.7)
    ax.fill(angles, ideal, alpha=0.05, color='#e94560')

    # Wrap long labels
    wrapped = [p.replace(" ", "\n") if len(p) > 12 else p for p in problems]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(wrapped, color='#d0d0d0', fontsize=11, fontweight='bold')

    for i, (angle, val) in enumerate(zip(angles[:-1], values[:-1])):
        pct = round(val * 100)
        ax.annotate(f'{pct}%', xy=(angle, val), xytext=(10, 10),
                    textcoords='offset points', color='#00d4aa', fontsize=12, fontweight='bold')

    ax.set_ylim(0, max(max(values), 0.3) * 1.2)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.set_yticklabels(['20%', '40%', '60%', '80%'], color='#555577', fontsize=9)
    ax.tick_params(colors='#555577')
    ax.spines['polar'].set_color('#333355')
    ax.grid(color='#333355', linewidth=0.5)

    ax.set_title("Favourite Problems Radar\nActual time vs balanced target",
                 color='#d0d0d0', fontsize=14, fontweight='bold', pad=30, y=1.08)

    legend = ax.legend(loc='lower right', bbox_to_anchor=(1.15, -0.05), fontsize=11,
                       facecolor='#1a1a2e', edgecolor='#333355', labelcolor='#d0d0d0')

    plt.tight_layout()
    plt.savefig(OUTPUT, dpi=150, facecolor='#0f0f1a', bbox_inches='tight')
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
