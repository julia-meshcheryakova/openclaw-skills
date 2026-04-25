---
name: usage-report
description: Generate weekly usage reports with charts from OpenClaw session logs. Tracks time across categories (work, health, learning, finance, etc.) with LLM-powered topic labeling and rich visual charts. Use when setting up usage tracking, running weekly reports, backfilling historical data, or customizing category mappings. Includes extract, label, and report pipeline scripts.
---

# usage-report

Generate weekly usage reports with charts from OpenClaw session logs. Tracks how you spend time across categories (work, health, learning, finance, etc.) with topic labeling via LLM and rich visual charts.

## Pipeline

```
Session JSONL logs → [extract] → [label] → [weekly-report]
```

1. **extract-usage.py** — parses session logs into activity blocks (extracted/YYYY-MM-DD.json)
2. **label-usage.py** — sends blocks to LLM for topic/category labeling (labeled/YYYY-MM-DD.json)
3. **weekly-report.py** — generates 4 weekly charts + 2 all-time charts (PNG files)

## Quick Start

```bash
# 1. Run setup (creates dirs, copies default configs)
python3 scripts/setup.py

# 2. Edit your category map
# ~/.openclaw/workspace/data/usage/category-map.json

# 3. Edit LLM config (if not using GITHUB_TOKEN)
# ~/.openclaw/workspace/data/usage/config.json

# 4. Backfill all history (one time)
python3 scripts/setup.py --backfill

# 5. Generate weekly report
python3 scripts/weekly-report.py
```

## Daily Usage

```bash
# Extract yesterday's sessions
python3 scripts/extract-usage.py

# Label yesterday's blocks
python3 scripts/label-usage.py

# Generate weekly report for current week
python3 scripts/weekly-report.py

# Report for a specific week
python3 scripts/weekly-report.py 2026-04-14

# All-time trend charts only
python3 scripts/weekly-report.py --alltime
```

## Workspace Paths

All paths are resolved relative to `$OPENCLAW_WORKSPACE` (or auto-detected):

| Path | Contents |
|------|----------|
| `data/usage/extracted/` | Raw activity blocks per day |
| `data/usage/labeled/` | LLM-labeled blocks per day |
| `data/usage/raw/` | Legacy raw JSONL (fallback) |
| `data/usage/category-map.json` | Your category → subcategories mapping |
| `data/usage/config.json` | LLM provider config |
| `exports/weekly/` | Weekly chart PNGs |
| `exports/alltime/` | All-time timeline & trend charts |

## Category Map

Format: **category → list of subcategories**. The scripts flatten this for lookups.

```json
{
  "work": ["career planning", "linkedin post", "interview prep"],
  "health": ["running", "gym", "physio"],
  "finance": ["tax", "isa", "sipp", "bills"],
  "config": ["openclaw setup", "bot setup", "cron jobs"],
  "learning": ["online course", "research"],
  "personal": ["trip planning", "calendar management"],
  "creative": ["ideation", "writing"],
  "social": ["chatting with friends", "group chat"],
  "side-projects": ["personal project", "prototype"]
}
```

New subcategories from the LLM are auto-resolved using keyword rules and appended to your map.

## LLM Config

`data/usage/config.json`:

```json
{
  "provider": "copilot",
  "model": "claude-sonnet-4",
  "apiKey": "$GITHUB_TOKEN",
  "baseUrl": "https://api.githubcopilot.com"
}
```

**Supported providers** (all use OpenAI-compatible chat format):
- `copilot` — GitHub Copilot (default, requires `GITHUB_TOKEN`)
- `openai` — OpenAI API (`https://api.openai.com/v1`)
- `anthropic` — Anthropic via compatible proxy

If no config file exists, the script falls back to `GITHUB_TOKEN` with Copilot.

`apiKey` supports `$ENV_VAR` syntax to read from environment.

## Charts Generated

**Weekly charts** (saved to `exports/weekly/`):
- `waterfall-YYYY-MM-DD.png` — Category time breakdown (horizontal bars)
- `engagement-YYYY-MM-DD.png` — Daily engagement blocks by time of day
- `topics-highlights-YYYY-MM-DD.png` — Category → top 3 topics breakdown
- `topics-roi-YYYY-MM-DD.png` — Topic value scores (color-coded red→green)

**All-time charts** (saved to `exports/alltime/`):
- `timeline.png` — Daily stacked bar chart with 7-day rolling average
- `category-trends.png` — Weekly hours per category (line chart)

## Automation (cron)

Run daily via cron to keep data current:

```cron
# Extract and label yesterday's data at 01:00
0 1 * * * OPENCLAW_WORKSPACE=/path/to/workspace python3 /path/to/skills/usage-report/scripts/extract-usage.py
5 1 * * * OPENCLAW_WORKSPACE=/path/to/workspace python3 /path/to/skills/usage-report/scripts/label-usage.py

# Weekly report every Monday at 07:00
0 7 * * 1 OPENCLAW_WORKSPACE=/path/to/workspace python3 /path/to/skills/usage-report/scripts/weekly-report.py
```

## Requirements

```
Python 3.11+
matplotlib
numpy
```

Install dependencies:
```bash
pip install matplotlib numpy
```
