#!/usr/bin/env python3
"""
Horizon scout heatmap: average score per stop × hour-of-day.

Run inside the container:
  docker exec sky-watcher python scout_heatmap.py

Or directly on the NAS (pass HIGHLIGHTS_DIR if needed):
  HIGHLIGHTS_DIR=/volume1/highlights python scout_heatmap.py
"""

import json
import os
from collections import defaultdict
from pathlib import Path

SCOUT_STATS = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights")) / "scout_stats.json"

RESET = "\033[0m"


def _load_records() -> list[dict]:
    if not SCOUT_STATS.exists():
        return []
    records = []
    with open(SCOUT_STATS) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _build_matrix(records: list[dict]) -> tuple[dict, int]:
    # acc[hour][stop] = [sum_score, count]
    acc: dict = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    n_stops = 0
    for r in records:
        h = r.get("hour", 0)
        stops = r.get("stops", [])
        n_stops = max(n_stops, len(stops))
        for i, score in enumerate(stops):
            acc[h][i][0] += score
            acc[h][i][1] += 1
    return acc, n_stops


def _cell_color(score: float, lo: float, hi: float) -> str:
    """24-bit ANSI background: blue (low) → yellow (mid) → red (high)."""
    t = (score - lo) / (hi - lo) if hi > lo else 0.5
    if t < 0.5:
        u = t * 2
        r, g, b = int(u * 255), int(u * 180), int((1 - u) * 200)
    else:
        u = (t - 0.5) * 2
        r, g, b = 255, int((1 - u) * 180), 0
    fg = "0;0;0" if t > 0.35 else "220;220;220"
    return f"\033[48;2;{r};{g};{b}m\033[38;2;{fg}m"


def print_heatmap(acc: dict, n_stops: int, n_records: int) -> None:
    all_avgs = {
        (h, s): acc[h][s][0] / acc[h][s][1]
        for h in acc for s in acc[h] if acc[h][s][1] > 0
    }
    if not all_avgs:
        print("No data yet — run the sky-watcher for a while first.")
        return

    lo = min(all_avgs.values())
    hi = max(all_avgs.values())
    active_hours = sorted(h for h in acc if any(acc[h][s][1] > 0 for s in range(n_stops)))

    print(f"\nHorizon Scout Heatmap  ({n_records} scans · score range {lo:.0f}–{hi:.0f})")
    print()

    # Header
    print(f"{'Hour':>5}  ", end="")
    for s in range(n_stops):
        print(f"  S{s+1:<2} ", end="")
    print("  scans")

    for h in active_hours:
        print(f"  {h:02d}h  ", end="")
        for s in range(n_stops):
            total, count = acc[h][s]
            if count > 0:
                avg = total / count
                color = _cell_color(avg, lo, hi)
                print(f"{color}{avg:4.0f} {RESET}", end="")
            else:
                print("  ·   ", end="")
        n = acc[h][0][1]
        print(f"  ({n})")

    # Best-stop summary
    print(f"\n  Best stop by hour (bar = avg score / 5):")
    for h in active_hours:
        candidates = {s: all_avgs[(h, s)] for s in range(n_stops) if (h, s) in all_avgs}
        if not candidates:
            continue
        best_s = max(candidates, key=candidates.__getitem__)
        best_v = candidates[best_s]
        bar = "█" * max(1, int(best_v / 5))
        print(f"  {h:02d}h  S{best_s+1}  {best_v:5.1f}  {bar}")

    print()


if __name__ == "__main__":
    records = _load_records()
    if not records:
        print(f"No scout stats found at {SCOUT_STATS}")
        print("The sky-watcher writes one record per horizon scan — give it some time.")
    else:
        print(f"Loaded {len(records)} scan records from {SCOUT_STATS}")
        acc, n_stops = _build_matrix(records)
        print_heatmap(acc, n_stops, len(records))
