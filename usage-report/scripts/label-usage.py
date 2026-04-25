#!/usr/bin/env python3
"""
label-usage.py — LLM labeler for usage blocks.

Reads extracted blocks from data/usage/extracted/YYYY-MM-DD.json,
calls LLM to assign topic, subcategory, and value to each block.
Writes labeled output to data/usage/labeled/YYYY-MM-DD.json.

Usage:
    python3 scripts/label-usage.py [YYYY-MM-DD]   (defaults to yesterday)
    python3 scripts/label-usage.py --all          (label all extracted dates)

LLM config is read from $OPENCLAW_WORKSPACE/data/usage/config.json.
Falls back to GITHUB_TOKEN with Copilot if no config found.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import urllib.request
import urllib.error

USER_TZ = ZoneInfo(os.environ.get("OPENCLAW_TZ", "UTC"))
BATCH_SIZE = 30


# ─── Path resolution ─────────────────────────────────────────────────────────

def find_workspace() -> Path:
    env = os.environ.get("OPENCLAW_WORKSPACE")
    if env:
        return Path(env)
    base = Path.home() / ".openclaw"
    candidates = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("workspace")]
    if candidates:
        return sorted(candidates)[0]
    return base / "workspace"


WORKSPACE = find_workspace()
EXTRACTED_DIR = WORKSPACE / "data" / "usage" / "extracted"
LABELED_DIR = WORKSPACE / "data" / "usage" / "labeled"
CAT_MAP_PATH = WORKSPACE / "data" / "usage" / "category-map.json"
MEMORY_DIR = WORKSPACE / "memory"
CONFIG_PATH = WORKSPACE / "data" / "usage" / "config.json"


# ─── Category map ─────────────────────────────────────────────────────────────

def _load_map_file(path: Path) -> dict:
    """Load a single category map file."""
    with open(path) as f:
        return json.load(f)


def _parse_map(data: dict) -> tuple[dict, list]:
    """Parse a category map (either format) into (subcat_to_cat, categories)."""
    subcat_to_cat = {}
    categories = []
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            # Inverted format: category → [subcategories]
            categories.append(k)
            for subcat in v:
                subcat_to_cat[subcat.lower().strip()] = k
        elif isinstance(v, str):
            # Legacy flat format: subcategory → category
            subcat_to_cat[k.lower().strip()] = v
            if v not in categories:
                categories.append(v)
    return subcat_to_cat, categories


def load_category_map() -> tuple[dict, list]:
    """Load category map. Merges skill defaults with user overrides.
    Checks category-map.json and subcategory-map.json (legacy name).
    User workspace map augments the skill's default map.
    """
    skill_dir = Path(__file__).parent.parent
    skill_default = skill_dir / "assets" / "category-map.json"

    # Find user map (try both filenames)
    user_path = None
    for name in ["category-map.json", "subcategory-map.json"]:
        candidate = WORKSPACE / "data" / "usage" / name
        if candidate.exists():
            user_path = candidate
            break

    # Start with skill defaults
    base_map = {}
    if skill_default.exists():
        base_map = _load_map_file(skill_default)

    # Merge user map on top
    if user_path:
        user_map = _load_map_file(user_path)
        for k, v in user_map.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list) and isinstance(base_map.get(k), list):
                # Merge subcategory lists
                merged = list(set(base_map[k] + v))
                base_map[k] = sorted(merged)
            else:
                base_map[k] = v
    elif not base_map:
        return {}, []

    return _parse_map(base_map)


# Common words to exclude from auto-derived keyword rules
_STOP_WORDS = {
    'the', 'and', 'for', 'with', 'from', 'into', 'that', 'this',
    'are', 'was', 'were', 'been', 'have', 'has', 'had', 'not',
    'but', 'all', 'can', 'her', 'his', 'how', 'its', 'may',
    'new', 'now', 'old', 'our', 'out', 'own', 'say', 'she',
    'too', 'use', 'way', 'who', 'did', 'get', 'let', 'put',
    'set', 'try', 'ask', 'own', 'any', 'day', 'got', 'him',
    'man', 'run', 'see', 'top', 'two', 'yet',
}


def _build_keyword_rules(subcat_map: dict, categories: list) -> dict:
    """Derive keyword rules from the category map (no hardcoded duplicates).
    Uses full subcategory phrases + individual words (filtered for quality)."""
    rules = {}
    for subcat, cat in subcat_map.items():
        if cat not in rules:
            rules[cat] = []
        # Add full subcategory phrase as a keyword (best match)
        if subcat not in rules[cat]:
            rules[cat].append(subcat)
        # Add individual words (min 4 chars, not stop words)
        for word in subcat.split():
            if len(word) >= 4 and word not in _STOP_WORDS and word not in rules[cat]:
                rules[cat].append(word)
    return rules


def resolve_category(subcategory: str, subcat_map: dict, categories: list) -> tuple[str, bool, bool]:
    """Resolve subcategory to category. Returns (category, is_known, auto_resolved)."""
    sub_lower = subcategory.lower().strip()
    if sub_lower in subcat_map:
        return subcat_map[sub_lower], True, False
    for key, cat in subcat_map.items():
        if key in sub_lower or sub_lower in key:
            return cat, True, False
    sub_words = set(sub_lower.split())
    for key, cat in subcat_map.items():
        key_words = set(key.split())
        if len(sub_words & key_words) >= 1 and len(key_words) <= 3:
            return cat, True, False
    if sub_lower in categories:
        return sub_lower, False, True
    keyword_rules = _build_keyword_rules(subcat_map, categories)
    for cat, keywords in keyword_rules.items():
        if any(kw in sub_lower for kw in keywords):
            _auto_add_to_map(subcategory, cat)
            return cat, False, True
    return 'unknown', False, False


def _auto_add_to_map(subcategory: str, category: str):
    """Auto-add a new subcategory entry to the map file (appends to category list)."""
    try:
        if not CAT_MAP_PATH.exists():
            return
        with open(CAT_MAP_PATH) as f:
            data = json.load(f)
        sub = subcategory.lower().strip()
        if category in data and isinstance(data[category], list):
            if sub not in [s.lower() for s in data[category]]:
                data[category].append(sub)
                with open(CAT_MAP_PATH, 'w') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─── LLM config ───────────────────────────────────────────────────────────────

def load_llm_config() -> dict:
    """Load LLM config from config.json, falling back to env/defaults."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # Expand $ENV_VAR references in apiKey
        api_key = cfg.get("apiKey", "")
        if api_key.startswith("$"):
            api_key = os.environ.get(api_key[1:], "")
        cfg["apiKey"] = api_key
        return cfg

    # Default: try GITHUB_TOKEN with Copilot
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("COPILOT_GITHUB_TOKEN")
    return {
        "provider": "copilot",
        "model": "claude-sonnet-4",
        "apiKey": token or "",
        "baseUrl": "https://api.githubcopilot.com",
    }


def call_llm(prompt: str, cfg: dict) -> str:
    """Call LLM API (OpenAI-compatible chat completions)."""
    token = cfg.get("apiKey", "")
    if not token:
        print("Error: no API key configured. Set GITHUB_TOKEN or configure data/usage/config.json", file=sys.stderr)
        sys.exit(1)

    base_url = cfg.get("baseUrl", "https://api.githubcopilot.com").rstrip("/")
    model = cfg.get("model", "claude-sonnet-4")
    provider = cfg.get("provider", "copilot")

    url = f"{base_url}/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4000,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if provider == "copilot":
        headers["Copilot-Integration-Id"] = "vscode-chat"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


# ─── Prompting ────────────────────────────────────────────────────────────────

def get_daily_notes(date_str: str) -> str:
    path = MEMORY_DIR / f"{date_str}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")[:2000]
    return ""


def build_prompt(date_str: str, blocks: list, daily_notes: str, categories: list) -> str:
    blocks_summary = []
    for i, b in enumerate(blocks):
        start = b["start"][11:16] if "T" in b["start"] else b["start"]
        end = b["end"][11:16] if "T" in b["end"] else b["end"]
        snippet = b.get("snippet", "")[:250]
        blocks_summary.append(
            f"{i+1}. {start}–{end} ({b.get('attention_minutes', b.get('active_minutes', 0))}m, {b['message_count']}msg): {snippet}"
        )

    blocks_text = "\n".join(blocks_summary)
    categories_text = ", ".join(categories) if categories else "work, personal, finance, health, learning, config, creative, social, side-projects"

    prompt = f"""Label each usage block with topic, category, and value.

Date: {date_str}

Categories (pick one): {categories_text}

Blocks:
{blocks_text}
"""

    if daily_notes:
        prompt += f"""
Daily notes for context:
{daily_notes}
"""

    prompt += f"""
For each block, return a JSON array with one object per block:
[
  {{"block": 1, "topic": "short label", "subcategory": "specific area", "value": 7}},
  ...
]

Rules:
- "topic" = SPECIFIC descriptive label (2-5 words) about WHAT was discussed, not HOW.
  BAD: "Telegram message processing", "Evening session", "system state check"
  GOOD: "Job interview prep", "ISA rates research", "Copilot CLI setup", "Trip planning"
  Focus on the SUBJECT MATTER, not the channel or time of day.
- "subcategory" = a specific area/project name. Examples:
  openclaw setup, career planning, tax, running, online course, trip planning,
  linkedin post, chatting with friends, personal project, etc.
  Be specific — use project/domain names when applicable.
- "value" = 1-10 how valuable/impactful this block was (10 = high impact, 1 = trivial/noise)
- If snippet is empty or unclear, use context from daily notes or mark topic as "unclear"
- Return ONLY the JSON array, no other text
"""
    return prompt


def parse_labels(response: str, block_count: int, subcat_map: dict, categories: list) -> list:
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if not match:
        print(f"Warning: could not parse LLM response:\n{response}", file=sys.stderr)
        return [{"topic": "unknown", "subcategory": "unknown", "category": "unknown", "value": 5}] * block_count

    try:
        labels = json.loads(match.group())
    except json.JSONDecodeError:
        print(f"Warning: invalid JSON in LLM response:\n{match.group()}", file=sys.stderr)
        return [{"topic": "unknown", "subcategory": "unknown", "category": "unknown", "value": 5}] * block_count

    result = []
    for i in range(block_count):
        if i < len(labels):
            label = labels[i]
            subcategory = label.get("subcategory", "unknown")
            category, is_known, auto_resolved = resolve_category(subcategory, subcat_map, categories)
            result.append({
                "topic": label.get("topic", "unknown"),
                "subcategory": subcategory,
                "category": category,
                "category_known": is_known or auto_resolved,
                "auto_resolved": auto_resolved,
                "value": max(1, min(10, int(label.get("value", 5)))),
            })
        else:
            result.append({"topic": "unknown", "subcategory": "unknown", "category": "unknown",
                           "category_known": False, "auto_resolved": False, "value": 5})
    return result


def label_blocks_batched(blocks: list, date_str: str, daily_notes: str,
                         subcat_map: dict, categories: list, cfg: dict) -> list:
    all_labels = []
    for i in range(0, len(blocks), BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        prompt = build_prompt(date_str, batch, daily_notes if i == 0 else "", categories)
        response = call_llm(prompt, cfg)
        labels = parse_labels(response, len(batch), subcat_map, categories)
        all_labels.extend(labels)
    return all_labels


# ─── Main labeling logic ──────────────────────────────────────────────────────

def label_date(date_str: str, cfg: dict):
    LABELED_DIR.mkdir(parents=True, exist_ok=True)

    extracted_path = EXTRACTED_DIR / f"{date_str}.json"
    if not extracted_path.exists():
        print(f"No extracted data for {date_str}, skipping.")
        return None

    with open(extracted_path) as f:
        data = json.load(f)

    blocks = data.get("blocks", [])
    if not blocks:
        print(f"No blocks for {date_str}, skipping.")
        return None

    daily_notes = get_daily_notes(date_str)
    subcat_map, categories = load_category_map()

    print(f"Labeling {date_str}: {len(blocks)} blocks ({(len(blocks) + BATCH_SIZE - 1) // BATCH_SIZE} batches)...")
    labels = label_blocks_batched(blocks, date_str, daily_notes, subcat_map, categories, cfg)

    unknown_subcats = []
    auto_resolved_subcats = []
    for block, label in zip(blocks, labels):
        block["topic"] = label["topic"]
        block["subcategory"] = label["subcategory"]
        block["category"] = label["category"]
        block["value"] = label["value"]
        if not label["category_known"] and not label["auto_resolved"]:
            unknown_subcats.append(label["subcategory"])
        elif label["auto_resolved"]:
            auto_resolved_subcats.append(f"{label['subcategory']} → {label['category']}")

    category_minutes = {}
    for b in blocks:
        cat = b["category"]
        category_minutes[cat] = category_minutes.get(cat, 0) + b.get("attention_minutes", b.get("active_minutes", 0))

    output = {
        "date": date_str,
        "total_span_minutes": data.get("total_span_minutes", 0),
        "total_attention_minutes": data.get("total_attention_minutes", 0),
        "total_messages": data["total_messages"],
        "block_count": data["block_count"],
        "span_hours": data["span_hours"],
        "category_minutes": {k: round(v, 1) for k, v in sorted(category_minutes.items(), key=lambda x: -x[1])},
        "unknown_subcategories": sorted(set(unknown_subcats)) if unknown_subcats else [],
        "auto_resolved_subcategories": sorted(set(auto_resolved_subcats)) if auto_resolved_subcats else [],
        "blocks": blocks,
    }

    out_path = LABELED_DIR / f"{date_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  Labeled: {out_path}")
    for cat, mins in sorted(category_minutes.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {round(mins, 1)}m")
    if unknown_subcats:
        print(f"  ⚠️  Unknown subcategories (need your input): {', '.join(sorted(set(unknown_subcats)))}")
    if auto_resolved_subcats:
        print(f"  ✅ Auto-resolved: {', '.join(sorted(set(auto_resolved_subcats)))}")

    return output


def main():
    args = sys.argv[1:]
    cfg = load_llm_config()

    if "--all" in args:
        dates = sorted(f.stem for f in EXTRACTED_DIR.glob("*.json"))
        print(f"Labeling {len(dates)} dates...\n")
        for d in dates:
            label_date(d, cfg)
    else:
        if args:
            date_str = args[0]
        else:
            yesterday = datetime.now(USER_TZ) - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")
        label_date(date_str, cfg)


if __name__ == "__main__":
    main()
