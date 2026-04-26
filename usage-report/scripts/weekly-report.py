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


from util import find_workspace


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
