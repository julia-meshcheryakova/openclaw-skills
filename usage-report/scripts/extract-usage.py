#!/usr/bin/env python3
"""
extract-usage.py — Extract usage data from OpenClaw session JSONL logs.

Usage:
    python3 scripts/extract-usage.py [YYYY-MM-DD]   (defaults to yesterday)
    python3 scripts/extract-usage.py --all          (process all dates found)

Paths are auto-detected:
  Sessions:  ~/.openclaw/agents/*/sessions/
  Output:    $OPENCLAW_WORKSPACE/data/usage/extracted/
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

GAP_MINUTES = 5

# User timezone — override via OPENCLAW_TZ env var (default: UTC)
USER_TZ = ZoneInfo(os.environ.get("OPENCLAW_TZ", "UTC"))


from util import find_workspace


def find_sessions_dirs() -> list:
    """Glob all agent session directories."""
    base = Path.home() / ".openclaw" / "agents"
    return list(base.glob("*/sessions"))


WORKSPACE = find_workspace()
SESSIONS_DIRS = find_sessions_dirs()
OUTPUT_DIR = WORKSPACE / "data" / "usage" / "extracted"


# ─── Parsing helpers ─────────────────────────────────────────────────────────

def parse_iso(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(USER_TZ)


def strip_snippet(text: str) -> str:
    """Strip OpenClaw envelope metadata from user messages (provider-agnostic)."""
    # Remove untrusted metadata blocks (Conversation info, Sender, Replied, Forwarded)
    text = re.sub(
        r"(?:Conversation info|Sender|Replied message|Forwarded message context)"
        r"\s*\(untrusted[^)]*\):\s*```json\s*?\{.*?\}\s*?```\s*",
        "", text, flags=re.DOTALL,
    )
    # Remove channel-prefixed timestamps: [Telegram ...], [Discord ...], [Signal ...], etc.
    text = re.sub(r"(?:^|\n)\[(?:Telegram|Discord|Signal|Slack|WhatsApp|IRC|Matrix|Teams)[^\]]*\]\s*", "\n", text)
    # Remove common envelope labels
    text = re.sub(r"(?:^|\n)User text:\s*\n?", "\n", text)
    text = re.sub(r"(?:^|\n)Transcript:\s*\n?", "\n", text)
    text = re.sub(r"(?:^|\n)\[Audio\]\s*\n?", "\n", text)
    text = re.sub(r"(?:^|\n)\[[^\]]{0,80}\]\s*", "\n", text)
    text = re.sub(r"^\[media attached:.*?\]\s*", "", text)
    text = re.sub(r"^System:\s*", "", text)
    # Remove leading JSON code blocks (metadata)
    text = re.sub(r"^```(?:json)?\s*\{[^}]*\}\s*```\s*", "", text, flags=re.DOTALL)
    return text.strip()


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts)
    return ""


def is_skippable_session(messages: list) -> bool:
    for role, text, _ in messages:
        if role == "user":
            lower = text[:500].lower()
            if any(kw in lower for kw in (
                "[subagent", "subagent context", "you are a subagent",
                "[subagent task]",
                "[cron:", "heartbeat", "read heartbeat.md",
                "nightly-workspace-review", "nightly workspace review",
                "weekly-optimization", "consolidation",
            )):
                return True
            break
    return False


def _is_noise_message(text: str) -> bool:
    lower = text[:200].lower().strip()
    if lower in ("heartbeat_ok", "no_reply"):
        return True
    return any(kw in lower for kw in (
        "<<<begin_openclaw_internal_context>>>",
        "[system] your previous turn",
        "[inter-session message]",
        "pre-compaction memory flush",
    ))


def _make_block(session_id, msgs, start, end, user_texts):
    span_minutes = round((end - start).total_seconds() / 60, 1)
    attention_minutes = 0.0
    for i in range(1, len(msgs)):
        gap = (msgs[i][2] - msgs[i-1][2]).total_seconds() / 60
        attention_minutes += min(gap, 3.0)
    attention_minutes = round(attention_minutes, 1)
    clean_texts = [ut for ut in user_texts if not _is_noise_message(ut)]
    snippets = []
    for ut in clean_texts:
        clean = strip_snippet(ut)
        if clean:
            snippets.append(clean[:200])
    snippet = " | ".join(snippets) if snippets else ""
    user_msgs_in_block = [m for m in msgs if m[0] == "user"]
    real_user_msgs = [m for m in user_msgs_in_block if not _is_noise_message(m[1])]
    if user_msgs_in_block and not real_user_msgs:
        return None
    return {
        "session_id": session_id,
        "start": to_local(start).isoformat(),
        "end": to_local(end).isoformat(),
        "span_minutes": span_minutes,
        "attention_minutes": attention_minutes,
        "message_count": len(msgs),
        "snippet": snippet,
    }


def cluster_blocks(session_id: str, messages: list) -> list:
    if not messages:
        return []
    messages = sorted(messages, key=lambda m: m[2])
    blocks = []
    block_start = messages[0][2]
    block_end = messages[0][2]
    block_msgs = [messages[0]]
    user_texts = []
    if messages[0][0] == "user":
        user_texts.append(messages[0][1])

    for msg in messages[1:]:
        role, text, dt = msg
        gap = (dt - block_end).total_seconds() / 60
        if gap < GAP_MINUTES:
            block_msgs.append(msg)
            block_end = dt
            if role == "user" and len(user_texts) < 8:
                user_texts.append(text)
        else:
            block = _make_block(session_id, block_msgs, block_start, block_end, user_texts)
            if block:
                blocks.append(block)
            block_start = dt
            block_end = dt
            block_msgs = [msg]
            user_texts = [text] if role == "user" else []

    block = _make_block(session_id, block_msgs, block_start, block_end, user_texts)
    if block:
        blocks.append(block)
    return blocks


def process_session_file(path: Path, target_date_local: str):
    messages = []
    session_id = path.stem
    if '.checkpoint.' in path.name:
        return None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "message":
                continue
            msg = entry.get("message", {})
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            ts_str = entry.get("timestamp")
            if ts_str:
                try:
                    dt_utc = parse_iso(ts_str)
                except ValueError:
                    ts_str = None

            if not ts_str:
                epoch_ms = msg.get("timestamp")
                if epoch_ms:
                    dt_utc = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
                else:
                    continue

            dt_local = to_local(dt_utc)
            if dt_local.strftime("%Y-%m-%d") != target_date_local:
                continue

            content = msg.get("content", "")
            text = extract_text(content)
            messages.append((role, text, dt_utc))

    if not messages:
        return None
    if is_skippable_session(messages):
        return None
    # Filter compaction dumps: >20 messages in same minute = compaction, not real activity
    minute_counts = Counter(dt.strftime("%Y%m%d%H%M") for _, _, dt in messages)
    compaction_minutes = {m for m, c in minute_counts.items() if c > 20}
    if compaction_minutes:
        messages = [(r, t, d) for r, t, d in messages if d.strftime("%Y%m%d%H%M") not in compaction_minutes]
    user_msgs = [m for m in messages if m[0] == "user"]
    if not user_msgs:
        return None
    return session_id, messages


def process_date(date_str: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date_str}.json"
    all_blocks = []

    for sessions_dir in SESSIONS_DIRS:
        for sf in sorted(sessions_dir.glob("*.jsonl")):
            result = process_session_file(sf, date_str)
            if result is None:
                continue
            session_id, messages = result
            blocks = cluster_blocks(session_id, messages)
            all_blocks.extend(blocks)

    all_blocks.sort(key=lambda b: b["start"])

    total_messages = sum(b["message_count"] for b in all_blocks)
    total_span = round(sum(b["span_minutes"] for b in all_blocks), 1)
    total_attention = round(sum(b["attention_minutes"] for b in all_blocks), 1)

    if all_blocks:
        first_start = datetime.fromisoformat(all_blocks[0]["start"])
        last_end = datetime.fromisoformat(all_blocks[-1]["end"])
        span_hours = round((last_end - first_start).total_seconds() / 3600, 2)
    else:
        span_hours = 0.0

    summary = {
        "date": date_str,
        "total_span_minutes": total_span,
        "total_attention_minutes": total_attention,
        "total_messages": total_messages,
        "block_count": len(all_blocks),
        "span_hours": span_hours,
        "blocks": all_blocks,
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    print(f"Date: {date_str}")
    print(f"  Blocks: {len(all_blocks)}")
    print(f"  Total messages: {total_messages}")
    print(f"  Span minutes: {total_span}")
    print(f"  Attention minutes: {total_attention}")
    print(f"  Span hours: {span_hours}")
    print(f"  Output: {out_path}")
    if all_blocks:
        print(f"  First block: {all_blocks[0]['start']} — {all_blocks[0]['snippet'][:60]!r}")
    print()
    return summary


def get_all_dates() -> list:
    dates = set()
    for sessions_dir in SESSIONS_DIRS:
        for sf in sessions_dir.glob("*.jsonl"):
            with open(sf, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "message":
                        continue
                    ts_str = entry.get("timestamp")
                    if ts_str:
                        try:
                            dt_utc = parse_iso(ts_str)
                            dates.add(to_local(dt_utc).strftime("%Y-%m-%d"))
                        except ValueError:
                            pass
    return sorted(dates)


def main():
    args = sys.argv[1:]
    if "--all" in args:
        print("Scanning all dates...")
        dates = get_all_dates()
        print(f"Found dates: {dates}\n")
        for d in dates:
            process_date(d)
    else:
        if args:
            date_str = args[0]
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                print(f"Error: invalid date '{date_str}', expected YYYY-MM-DD")
                sys.exit(1)
        else:
            yesterday = datetime.now(USER_TZ) - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")
        process_date(date_str)


if __name__ == "__main__":
    main()
