#!/usr/bin/env python3
"""
weekly-report.py — Generate visual weekly usage reports with charts.

Usage:
  python3 scripts/weekly-report.py                  # current week
  python3 scripts/weekly-report.py 2026-04-13       # week containing this date
  python3 scripts/weekly-report.py --alltime        # all-time charts only

Paths:
  Input:   $OPENCLAW_WORKSPACE/data/usage/labeled/ (and raw/ as fallback)
  Output:  $OPENCLAW_WORKSPACE/exports/weekly/
           $OPENCLAW_WORKSPACE/exports/alltime/
"""

import sys
import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.ticker as ticker


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


WORKSPACE   = find_workspace()
DATA_DIR    = WORKSPACE / 'data' / 'usage' / 'raw'
LABELED_DIR = WORKSPACE / 'data' / 'usage' / 'labeled'
WEEKLY_DIR  = WORKSPACE / 'exports' / 'weekly'
ALLTIME_DIR = WORKSPACE / 'exports' / 'alltime'

WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
ALLTIME_DIR.mkdir(parents=True, exist_ok=True)

# ─── Theme ───────────────────────────────────────────────────────────────────
BG     = '#0f0f1a'
PANEL  = '#161625'
TEXT   = '#d0d0d0'
ACCENT = '#00d4aa'
RED    = '#e94560'
YELLOW = '#f39c12'
MUTED  = '#555577'
BLUE   = '#3498db'
PURPLE = '#9b59b6'

CATEGORY_COLORS = {
    'config':        '#6C5CE7',
    'work':          '#0984E3',
    'personal':      '#00B894',
    'creative':      '#E17055',
    'learning':      '#FDCB6E',
    'side-projects': '#E84393',
    'finance':       '#74B9FF',
    'health':        '#E74C3C',
    'social':        '#A29BFE',
    'admin':         '#B2BEC3',
}

STACK_ORDER = ['config', 'work', 'finance', 'learning', 'creative', 'personal', 'health', 'social', 'side-projects']

CATEGORY_LABELS = {
    'work':          'Work/Career',
    'finance':       'Finance',
    'learning':      'Learning',
    'creative':      'Creative',
    'personal':      'Personal',
    'health':        'Health/Sport',
    'health/sport':  'Health/Sport',
    'social':        'Social',
    'config':        'Config',
    'side-projects': 'Side-projects',
}

# ─── Category aliases ─────────────────────────────────────────────────────────
CATEGORY_ALIASES = {'health': 'health/sport'}

def _normalize_cat(cat: str) -> str:
    return CATEGORY_ALIASES.get(cat, cat)

# ─── Data loading ─────────────────────────────────────────────────────────────

def load_day(d: date) -> list[dict]:
    labeled_path = LABELED_DIR / f'{d.isoformat()}.json'
    if labeled_path.exists():
        with open(labeled_path) as f:
            data = json.load(f)
        rows = []
        for b in data.get('blocks', []):
            start = b.get('start', '')
            ts = '00:00'
            if 'T' in start:
                ts = start.split('T')[1][:5]
            row = {
                'ts': ts,
                'tz': 'local',
                'topic': b.get('topic', b.get('snippet', 'unknown')),
                'subcategory': b.get('subcategory', b.get('topic', 'unknown')),
                'category': _normalize_cat(b.get('category', 'personal')),
                'duration_est_min': b.get('attention_minutes', b.get('active_minutes', b.get('span_minutes', 0))),
                'value': b.get('value', 5),
            }
            rows.append(row)
        return rows

    # Fallback to raw JSONL
    path = DATA_DIR / f'{d.isoformat()}.jsonl'
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def load_week(week_start: date) -> list[dict]:
    rows = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        for r in load_day(d):
            r['_date'] = d
            rows.append(r)
    return rows


def load_all() -> list[dict]:
    rows = []
    seen = set()
    for path in sorted(LABELED_DIR.glob('*.json')):
        d = date.fromisoformat(path.stem)
        seen.add(d)
        for r in load_day(d):
            r['_date'] = d
            rows.append(r)
    for path in sorted(DATA_DIR.glob('*.jsonl')):
        d = date.fromisoformat(path.stem)
        if d not in seen:
            for r in load_day(d):
                r['_date'] = d
                rows.append(r)
    return rows


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def hours(rows) -> float:
    return sum(r.get('duration_est_min', 0) for r in rows) / 60.0


def category_hours(rows) -> dict:
    ch = defaultdict(float)
    for r in rows:
        cat = r.get('category', 'admin')
        ch[cat] += r.get('duration_est_min', 0) / 60.0
    return dict(ch)


def topic_hours(rows) -> dict:
    th = defaultdict(float)
    for r in rows:
        topic = r.get('topic', 'Unknown')
        th[topic] += r.get('duration_est_min', 0) / 60.0
    return dict(th)


# ─── Style helpers ────────────────────────────────────────────────────────────

def apply_dark(fig, ax):
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TEXT)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    ax.title.set_color(TEXT)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']:
        ax.spines[spine].set_color(MUTED)
    ax.tick_params(axis='both', colors=TEXT)
    ax.grid(alpha=0.15, color=MUTED)


def save(fig, path: Path):
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor=BG)
    plt.close(fig)
    print(f'  ✓ {path.relative_to(WORKSPACE)}')


# ─── Chart 1: Category breakdown (horizontal bar) ────────────────────────────

def chart_waterfall(rows, week_start: date):
    ch = category_hours(rows)
    total = hours(rows)
    items = [(cat, h) for cat, h in ch.items() if h > 0.01]
    items.sort(key=lambda x: x[1], reverse=True)
    if not items:
        print('  ⚠ No data for category breakdown')
        return None

    labels = [CATEGORY_LABELS.get(cat, cat) for cat, _ in items]
    values = [h for _, h in items]
    colors = [CATEGORY_COLORS.get(cat, MUTED) for cat, _ in items]

    n = len(items)
    fig_h = max(5, n * 0.6 + 2)
    fig, ax = plt.subplots(figsize=(12, fig_h))
    apply_dark(fig, ax)

    ys = list(range(n))
    bars = ax.barh(ys, values, color=colors, height=0.6, zorder=3)
    max_h = max(values) if values else 1

    for i, (bar, v) in enumerate(zip(bars, values)):
        pct = f'{v/total*100:.0f}%' if total > 0 else ''
        label = f'{v:.1f}h ({pct})'
        if v > max_h * 0.3:
            ax.text(v - max_h * 0.01, i, label,
                    ha='right', va='center', color='white', fontsize=10, fontweight='bold', zorder=4)
        else:
            ax.text(v + max_h * 0.02, i, label,
                    ha='left', va='center', color=TEXT, fontsize=10, fontweight='bold', zorder=4)

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, color=TEXT, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel('Hours', color=TEXT)
    ax.set_title(f'Where Your Time Went — {total:.1f}h total',
                 color=TEXT, fontsize=14, fontweight='bold', pad=12)
    ax.set_xlim(0, max_h * 1.35)
    ax.grid(axis='x', alpha=0.15, color=MUTED)
    ax.grid(axis='y', visible=False)
    apply_dark(fig, ax)

    out = WEEKLY_DIR / f'waterfall-{week_start.isoformat()}.png'
    save(fig, out)
    return out


# ─── Chart 2: Engagement blocks ──────────────────────────────────────────────

def parse_time(ts_str: str) -> float:
    h, m = ts_str.split(':')
    return int(h) + int(m) / 60.0


def chart_engagement(rows, week_start: date):
    fig, ax = plt.subplots(figsize=(16, 8))
    apply_dark(fig, ax)

    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    days = [week_start + timedelta(days=i) for i in range(7)]

    total_sessions = 0
    total_active_h = 0.0
    active_days = 0

    for day_idx, d in enumerate(days):
        day_rows = [r for r in rows if r.get('_date') == d]
        if not day_rows:
            continue

        time_cats = []
        for r in day_rows:
            ts = r.get('ts', '')
            cat = r.get('category', 'personal')
            if ts:
                try:
                    time_cats.append((parse_time(ts), cat))
                except Exception:
                    pass

        if not time_cats:
            continue

        time_cats.sort(key=lambda x: x[0])
        times = [tc[0] for tc in time_cats]
        active_days += 1

        GAP = 20 / 60.0
        PAD = 5 / 60.0
        blocks = []
        block_start = times[0]
        block_end   = times[0]
        block_entries = [time_cats[0]]

        for tc in time_cats[1:]:
            t = tc[0]
            if t - block_end > GAP:
                blocks.append((block_start, block_end, block_entries))
                block_start = t
                block_end   = t
                block_entries = [tc]
            else:
                block_end = t
                block_entries.append(tc)
        blocks.append((block_start, block_end, block_entries))

        total_sessions += len(blocks)
        day_active = 0.0

        for (bs, be, bentries) in blocks:
            padded_start = max(6.0, bs - PAD)
            padded_end   = min(24.0, be + PAD)
            width = padded_end - padded_start
            day_active += width

            cat_counts = defaultdict(int)
            for _, cat in bentries:
                cat_counts[cat] += 1
            dominant_cat = max(cat_counts, key=cat_counts.get)
            color = CATEGORY_COLORS.get(dominant_cat, BLUE)

            y_center = (6 - day_idx)
            patch = FancyBboxPatch(
                (padded_start, y_center - 0.38),
                width, 0.76,
                boxstyle='round,pad=0.02',
                facecolor=color,
                edgecolor='none',
                alpha=0.85,
                zorder=3
            )
            ax.add_patch(patch)
            if width >= 0.8:
                cx = padded_start + width / 2
                ax.text(cx, y_center, str(len(bentries)),
                        ha='center', va='center', color='white',
                        fontsize=9, fontweight='bold', zorder=4)

        total_active_h += day_active
        ax.text(24.1, 6 - day_idx, f'{day_active:.1f}h',
                va='center', ha='left', color=TEXT, fontsize=9)

    ax.set_xlim(6, 24.8)
    ax.set_ylim(-0.6, 6.6)
    ax.set_yticks(range(7))
    ax.set_yticklabels(day_names[::-1], color=TEXT, fontsize=11)
    ax.set_xticks(range(6, 25, 2))
    ax.set_xticklabels([f'{h:02d}:00' for h in range(6, 25, 2)], color=TEXT, fontsize=9)
    ax.set_xlabel('Time of day', color=TEXT)
    ax.set_title(
        'Active Engagement Blocks\nWhen you\'re actually talking (>20 min gap = new block)',
        color=TEXT, fontsize=13, fontweight='bold', pad=12
    )

    avg_active = total_active_h / max(active_days, 1)
    avg_sessions = total_sessions / max(active_days, 1)
    stats = f'Avg active: {avg_active:.1f}h/day  |  Total sessions: {total_sessions}  |  Avg {avg_sessions:.1f} sessions/day'
    ax.text(0.5, -0.08, stats, transform=ax.transAxes,
            ha='center', va='top', color=MUTED, fontsize=10)

    apply_dark(fig, ax)
    out = WEEKLY_DIR / f'engagement-{week_start.isoformat()}.png'
    save(fig, out)
    return out


# ─── Chart 3: Category → Topic Breakdown ────────────────────────────────────

def chart_topic_highlights(rows, week_start: date):
    cat_topics = defaultdict(lambda: defaultdict(float))
    for r in rows:
        cat = r.get('category', 'personal')
        topic = r.get('topic', 'unknown')
        mins = r.get('duration_est_min', 0)
        cat_topics[cat][topic] += mins / 60.0

    if not cat_topics:
        print('  ⚠ No topics data for this week')
        return None

    cat_order = sorted(cat_topics.keys(), key=lambda c: sum(cat_topics[c].values()), reverse=True)

    display_rows = []
    for cat in cat_order:
        topics = cat_topics[cat]
        cat_total = sum(topics.values())
        if cat_total < 0.01:
            continue
        color = CATEGORY_COLORS.get(cat, MUTED)
        cat_label = CATEGORY_LABELS.get(cat, cat)
        display_rows.append((f'{cat_label}  ({cat_total:.1f}h)', cat_total, color, True))
        sorted_topics = sorted(topics.items(), key=lambda x: -x[1])[:3]
        for topic, h in sorted_topics:
            if h < 0.01:
                continue
            name = topic[:45] + '…' if len(topic) > 45 else topic
            display_rows.append((f'    {name}', h, color, False))

    n = len(display_rows)
    if n == 0:
        return None

    fig_h = max(6, n * 0.4 + 2)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    apply_dark(fig, ax)
    max_h = max(h for _, h, _, _ in display_rows)

    for i, (label, h, color, is_header) in enumerate(display_rows):
        y = n - 1 - i
        alpha = 1.0 if is_header else 0.6
        height = 0.7 if is_header else 0.5
        ax.barh(y, h, color=color, height=height, alpha=alpha, zorder=3)
        if h > max_h * 0.25:
            ax.text(h - max_h * 0.01, y, f'{h:.1f}h',
                    ha='right', va='center', color='white', fontsize=9,
                    fontweight='bold' if is_header else 'normal', zorder=4)
        else:
            ax.text(h + max_h * 0.02, y, f'{h:.1f}h',
                    ha='left', va='center', color=TEXT, fontsize=9, zorder=4)

    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in display_rows][::-1], color=TEXT, fontsize=9)
    ax.set_xlabel('Hours', color=TEXT)
    ax.set_title('Category → Topic Breakdown',
                 color=TEXT, fontsize=13, fontweight='bold', pad=12)
    ax.set_xlim(0, max_h * 1.4)
    ax.grid(axis='x', alpha=0.15, color=MUTED)
    ax.grid(axis='y', visible=False)
    apply_dark(fig, ax)

    out = WEEKLY_DIR / f'topics-highlights-{week_start.isoformat()}.png'
    save(fig, out)
    return out


# ─── Chart 4: Topic Value Scores ─────────────────────────────────────────────

CATEGORY_VALUE_DEFAULTS = {
    'work': 7, 'learning': 8, 'creative': 7, 'finance': 6,
    'personal': 5, 'health': 6, 'side-projects': 6, 'config': 4, 'social': 5,
}
OUTCOME_KEYWORDS = ['submitted', 'created', 'built', 'sent', 'delivered', 'completed', 'fixed']


def estimate_topic_value(topic: str, category: str, total_mins: float) -> int:
    base = CATEGORY_VALUE_DEFAULTS.get(category, 5)
    low = topic.lower()
    if any(kw in low for kw in OUTCOME_KEYWORDS):
        base += 1
    if total_mins > 60:
        base += 1
    return min(base, 10)


def chart_value_scores(rows, week_start: date):
    th = defaultdict(lambda: {'hours': 0.0, 'mins': 0.0, 'category': 'personal', 'values': []})
    for r in rows:
        subcat = r.get('subcategory', r.get('topic', 'Unknown'))
        mins = r.get('duration_est_min', 0)
        th[subcat]['hours'] += mins / 60.0
        th[subcat]['mins']  += mins
        th[subcat]['category'] = r.get('category', 'personal')
        th[subcat]['values'].append(r.get('value', 5))

    if not th:
        return None

    topic_data = []
    for name, info in th.items():
        if info['values']:
            v = round(sum(info['values']) / len(info['values']))
        else:
            v = estimate_topic_value(name, info['category'], info['mins'])
        topic_data.append({'name': name, 'hours': info['hours'], 'value': v, 'category': info['category']})

    topic_data.sort(key=lambda x: x['hours'], reverse=True)
    top12 = topic_data[:12]
    if not top12:
        return None

    n = len(top12)
    fig_h = max(6, n * 0.5 + 2)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    apply_dark(fig, ax)

    cmap = LinearSegmentedColormap.from_list('roi', [RED, YELLOW, ACCENT], N=256)
    max_h = max(t['hours'] for t in top12)

    for rank, td in enumerate(top12):
        y = n - 1 - rank
        v = td['value']
        h = td['hours']
        norm_v = (v - 1) / 9.0
        color = cmap(norm_v)
        ax.barh(y, h, color=color, height=0.6, zorder=3)
        if h > max_h * 0.2:
            ax.text(h - max_h * 0.01, y, f'{v}/10',
                    ha='right', va='center', color='white', fontsize=9, fontweight='bold', zorder=4)
        else:
            ax.text(h + max_h * 0.02, y, f'{h:.1f}h · {v}/10',
                    ha='left', va='center', color=TEXT, fontsize=9, fontweight='bold', zorder=4)

    names = [f"{td['name'][:40]}" for td in top12]
    ax.set_yticks(list(range(n)))
    ax.set_yticklabels(names[::-1], color=TEXT, fontsize=9)
    ax.set_xlabel('Hours', color=TEXT)
    ax.set_title('Topic Value Scores\nColor: red=low value, green=high value',
                 color=TEXT, fontsize=13, fontweight='bold', pad=12)
    ax.set_xlim(0, max_h * 1.4)
    ax.grid(axis='x', alpha=0.15, color=MUTED)
    ax.grid(axis='y', visible=False)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(1, 10))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.02, pad=0.01)
    cbar.ax.set_ylabel('Value score', color=TEXT, fontsize=9)
    cbar.ax.yaxis.set_tick_params(color=TEXT)
    cbar.ax.tick_params(colors=TEXT)
    cbar.outline.set_edgecolor(MUTED)

    apply_dark(fig, ax)
    out = WEEKLY_DIR / f'topics-roi-{week_start.isoformat()}.png'
    save(fig, out)
    return out


# ─── Chart 5: Timeline (all-time stacked bar) ────────────────────────────────

def chart_timeline(all_rows):
    if not all_rows:
        print('  ⚠ No data for timeline')
        return

    dates = sorted(set(r['_date'] for r in all_rows))
    d_min, d_max = dates[0], dates[-1]
    all_days = []
    cur = d_min
    while cur <= d_max:
        all_days.append(cur)
        cur += timedelta(days=1)

    day_cat = {d: defaultdict(float) for d in all_days}
    for r in all_rows:
        d = r['_date']
        cat = r.get('category', 'admin')
        day_cat[d][cat] += r.get('duration_est_min', 0) / 60.0

    xs = np.arange(len(all_days))
    totals = np.array([sum(day_cat[d].values()) for d in all_days])

    fig, ax = plt.subplots(figsize=(14, 5))
    apply_dark(fig, ax)

    bottoms = np.zeros(len(all_days))
    for cat in STACK_ORDER:
        vals = np.array([day_cat[d].get(cat, 0.0) for d in all_days])
        if vals.sum() == 0:
            continue
        ax.bar(xs, vals, bottom=bottoms, color=CATEGORY_COLORS[cat],
               label=cat, width=0.8, zorder=3)
        bottoms += vals

    rolling = np.convolve(totals, np.ones(7)/7, mode='same')
    if len(xs) >= 7:
        ax.plot(xs, rolling, color='#aaaaaa', linestyle='--', linewidth=1.5,
                label='7-day avg', zorder=5)

    ax.set_xticks(xs)
    x_labels = []
    for d in all_days:
        label = d.strftime('%-d')
        if d.weekday() >= 5:
            label = d.strftime('%-d %b')
        x_labels.append(label)
    ax.set_xticklabels(x_labels, rotation=90, ha='center', color=TEXT, fontsize=7)
    for i, d in enumerate(all_days):
        if d.weekday() >= 5:
            ax.get_xticklabels()[i].set_fontweight('bold')
            ax.get_xticklabels()[i].set_color(ACCENT)
    for i, d in enumerate(all_days):
        if d.weekday() == 0 and i > 0:
            ax.axvline(i - 0.5, color=MUTED, linewidth=0.5, linestyle=':', alpha=0.5, zorder=1)

    ax.set_ylabel('Hours', color=TEXT)
    ax.set_title('Daily Usage (All Time)', color=TEXT, fontsize=14, fontweight='bold', pad=12)
    legend = ax.legend(loc='upper left', framealpha=0.2, facecolor=PANEL,
                       labelcolor=TEXT, fontsize=8)
    legend.get_frame().set_edgecolor(MUTED)
    apply_dark(fig, ax)

    out = ALLTIME_DIR / 'timeline.png'
    save(fig, out)


# ─── Chart 6: Category trends (all-time) ─────────────────────────────────────

def chart_category_trends(all_rows):
    if not all_rows:
        print('  ⚠ No data for category trends')
        return

    week_cat = defaultdict(lambda: defaultdict(float))
    for r in all_rows:
        d = r['_date']
        ws = week_start_of(d)
        cat = r.get('category', 'admin')
        week_cat[ws][cat] += r.get('duration_est_min', 0) / 60.0

    weeks = sorted(week_cat.keys())
    if not weeks:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    apply_dark(fig, ax)

    xs = np.arange(len(weeks))
    for cat in STACK_ORDER:
        vals = np.array([week_cat[w].get(cat, 0.0) for w in weeks])
        if vals.sum() < 0.5:
            continue
        ax.plot(xs, vals, color=CATEGORY_COLORS[cat], label=cat,
                marker='o', markersize=5, linewidth=2, zorder=3)

    ax.set_xticks(xs)
    ax.set_xticklabels([w.strftime('%-d %b') for w in weeks],
                       rotation=45, ha='right', color=TEXT, fontsize=9)
    ax.set_ylabel('Hours / week', color=TEXT)
    ax.set_title('Category Trends — Weekly Hours', color=TEXT, fontsize=14,
                 fontweight='bold', pad=12)
    legend = ax.legend(loc='upper left', framealpha=0.2, facecolor=PANEL,
                       labelcolor=TEXT, fontsize=9)
    legend.get_frame().set_edgecolor(MUTED)
    apply_dark(fig, ax)

    out = ALLTIME_DIR / 'category-trends.png'
    save(fig, out)


# ─── Text summary ─────────────────────────────────────────────────────────────

def print_summary(rows, week_start: date, prev_rows):
    week_end = week_start + timedelta(days=6)
    ws_label = week_start.strftime('%a %-d %b')
    we_label = week_end.strftime('%a %-d %b')
    total_h = hours(rows)
    avg_h = total_h / 7
    ch = category_hours(rows)

    def pct(v):
        return f'{v/total_h*100:.0f}%' if total_h > 0 else '0%'

    print(f'\n📊 Weekly Report — {ws_label} – {we_label}')
    print(f'\n**{total_h:.1f}h total** · {avg_h:.1f}h/day avg · {len(rows)} events')
    print('\n**Where time went:**')
    for cat, h in sorted(ch.items(), key=lambda x: -x[1]):
        if h < 0.01:
            continue
        emoji = {'work': '💼', 'finance': '💰', 'learning': '📚', 'creative': '🎨',
                 'personal': '🟢', 'health': '❤️', 'social': '💬', 'config': '🟣',
                 'side-projects': '🚀'}.get(cat, '⬜')
        print(f'{emoji} {cat.capitalize()} — {h:.1f}h ({pct(h)})')

    th = topic_hours(rows)
    top5 = sorted(th.items(), key=lambda x: x[1], reverse=True)[:5]
    print('\n**Top 5 topics:**')
    for i, (t, h_) in enumerate(top5, 1):
        print(f'{i}. {t} — {h_:.1f}h')

    if prev_rows is not None:
        prev_total = hours(prev_rows)
        diff_total = total_h - prev_total
        sign = '+' if diff_total >= 0 else ''
        print('\n**vs last week:**')
        if prev_total > 0:
            print(f'• Total: {prev_total:.1f}h → {total_h:.1f}h ({sign}{diff_total/prev_total*100:.0f}%)')
        else:
            print(f'• Total: {prev_total:.1f}h → {total_h:.1f}h')
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    alltime_only = '--alltime' in args
    date_args = [a for a in args if a != '--alltime']

    if date_args:
        ref_date = date.fromisoformat(date_args[0])
    else:
        ref_date = date.today()

    ws = week_start_of(ref_date)
    prev_ws = ws - timedelta(weeks=1)
    all_rows = load_all()

    if alltime_only:
        print('\n📈 All-time charts...')
        chart_timeline(all_rows)
        chart_category_trends(all_rows)
        return

    print(f'\n📊 Weekly report for week of {ws.isoformat()}...')
    rows = load_week(ws)
    prev_rows = load_week(prev_ws)

    if not rows:
        print(f'  ⚠ No data found for week {ws.isoformat()} – {(ws+timedelta(6)).isoformat()}')

    print('\nGenerating weekly charts...')
    chart_waterfall(rows, ws)
    chart_engagement(rows, ws)
    chart_topic_highlights(rows, ws)
    chart_value_scores(rows, ws)

    print('\nGenerating all-time charts...')
    chart_timeline(all_rows)
    chart_category_trends(all_rows)

    print_summary(rows, ws, prev_rows)


if __name__ == '__main__':
    main()
