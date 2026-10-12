"""Summarize Locust reports: steady-state throughput and latency after the login phase.

Locust's totals include the start of each run, when every virtual user signs in (bcrypt). This script uses the
per-second history instead: the request rate over the last `--window` seconds, and the median of the rolling
p50/p95/p99 values in that window. It also prints the totals and failures from the stats file.

Usage: python loadtest/summarize.py loadtest/reports/R_20261008_151924 [--window 40]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
from pathlib import Path


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def steady(history: Path, window: int) -> dict:
    rows = [r for r in csv.DictReader(history.open(encoding="utf-8")) if r["Name"] == "Aggregated"]
    rows = [r for r in rows if _num(r["Total Request Count"]) is not None]
    if len(rows) < 3:
        return {}
    end = rows[-1]
    t_end = float(end["Timestamp"])
    start = next((r for r in rows if float(r["Timestamp"]) >= t_end - window), rows[0])
    dt = t_end - float(start["Timestamp"]) or 1.0
    win = [r for r in rows if float(r["Timestamp"]) >= t_end - window]

    def med(col: str) -> float | None:
        vals = [v for v in (_num(r[col]) for r in win) if v is not None]
        return round(statistics.median(vals)) if vals else None

    reqs = float(end["Total Request Count"]) - float(start["Total Request Count"])
    fails = float(end["Total Failure Count"]) - float(start["Total Failure Count"])
    return {"users": int(float(end["User Count"])), "rps": round(reqs / dt, 1), "fail_rps": round(fails / dt, 2),
            "p50_ms": med("50%"), "p95_ms": med("95%"), "p99_ms": med("99%")}


def totals(stats: Path) -> dict:
    out = {}
    for r in csv.DictReader(stats.open(encoding="utf-8")):
        out[r["Name"]] = {"n": int(r["Request Count"]), "fails": int(r["Failure Count"]), "p50": _num(r["50%"]),
                          "p95": _num(r["95%"]), "p99": _num(r["99%"]), "rps": round(float(r["Requests/s"]), 1)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--window", type=int, default=40)
    ap.add_argument("--endpoints", action="store_true", help="also print the totals of each endpoint")
    args = ap.parse_args()
    for hist in sorted(glob.glob(f"{args.prefix}*_stats_history.csv")):
        run = hist[: -len("_stats_history.csv")]
        s = steady(Path(hist), args.window)
        t = totals(Path(run + "_stats.csv")) if Path(run + "_stats.csv").exists() else {}
        agg = t.get("Aggregated", {})
        summ = Path(run + "_summary.json")
        extra = json.loads(summ.read_text(encoding="utf-8")) if summ.exists() else {}
        print(f"{Path(run).name}: steady {s}  | total n={agg.get('n')} fails={agg.get('fails')} "
              f"p95={agg.get('p95')} | replicas={extra.get('replicas')} modes={extra.get('chat_modes')}")
        if args.endpoints:
            for name, v in t.items():
                print(f"    {name[:40]:40} {v}")


if __name__ == "__main__":
    main()
