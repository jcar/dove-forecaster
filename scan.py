#!/usr/bin/env python3
"""Score all four arcs across recent + forecast days. Phase 3, step 1."""
import sys
from statistics import mean
from dove.geo import arc_points
from dove.weather import OpenMeteo
from dove.push import daily_features, score_day, Reservoir

PAST, FUTURE = int(sys.argv[1]) if len(sys.argv) > 1 else 24, 7


def arc_daily(arc):
    """Score EVERY sample point independently, then average the scores.

    Averaging weather across a 600-mile arc first would smear the frontal
    boundary out of existence - a front that has crossed 2 of 5 points looks
    like a weak front at all 5. Score first, average second.
    """
    series = OpenMeteo(mode="forecast").hourly(
        arc["points"], past_days=PAST, forecast_days=FUTURE)
    per_point = [daily_features(s["hourly"]) for s in series]
    dates = sorted(set.intersection(*[set(p) for p in per_point]))
    res, rows = Reservoir(), {}
    for i, d in enumerate(dates):
        if i == 0:
            continue
        pd = dates[i - 1]
        ss = [score_day(p[d], p[pd], arc["mean_lat"], d, res.level) for p in per_point]
        rows[d] = {
            "raw": mean(s["raw"] for s in ss),
            "gate": ss[0]["gate"], "reservoir": res.level,
            "index": mean(s["index"] for s in ss),
            "components": {k: mean(s["components"][k] for s in ss) for k in ss[0]["components"]},
            "obs": {k: mean(s["obs"][k] for s in ss) for k in ss[0]["obs"]},
        }
        res.debit(rows[d]["raw"] * rows[d]["gate"])
    return rows


def main():
    arcs = arc_points()
    table = {idx: arc_daily(arc) for idx, arc in arcs.items()}
    all_dates = sorted(set().union(*[set(r) for r in table.values()]))

    print(f"\n  DOVE MIGRATION FORECASTER — Push Index by arc  (Dallas, {PAST}d back / {FUTURE}d fwd)")
    print("  " + "-" * 74)
    print(f"  {'date':<12}" + "".join(f"{'Arc'+str(i):>9}" for i in arcs) + "     notes")
    print("  " + "-" * 74)
    for d in all_dates:
        cells = ""
        for i in arcs:
            s = table[i].get(d)
            cells += f"{s['index']:>9.0f}" if s else f"{'-':>9}"
        best = max((table[i].get(d, {}).get("index", 0), i) for i in arcs)
        note = ""
        if best[0] >= 35:
            s = table[best[1]][d]["obs"]
            note = f"  arc{best[1]}: {s['push_mph']:.0f}mph S-push, {s['temp_drop']:.0f}F drop, {s['pres_rise']:+.1f}mb"
        print(f"  {d:<12}{cells}{note}")
    print("  " + "-" * 74)
    for i, arc in arcs.items():
        print(f"  Arc {i} ({arc['dist_mi']:>3} mi, {arc['mean_lat']:.1f}N) {arc['label']}")


main()
