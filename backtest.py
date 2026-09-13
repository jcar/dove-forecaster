#!/usr/bin/env python3
"""Score historical seasons from the ERA5 archive.

Test 1a (this file): is the METEOROLOGY sound? Runs without any bird data.
If measured front speeds across many seasons cluster in the physically
sane 20-35 mph band, the passage detector works. If they all pile up near
10 mph, the detector is biased and every arrival date we have produced is
wrong.

Test 1b (blocked on eBird) grades arrival dates against dove density.
"""
import json
import os
import sys
import time
from datetime import timedelta
from statistics import mean, median

from dove.geo import arc_points
from dove.weather import OpenMeteo
from dove.push import daily_features, score_day, Reservoir
from dove.front import arc_passages_season, cluster_fronts, front_speed_mph

SEASON = ("08-15", "11-15")
OUT = "data/backtest"


def season(year, arcs, pause=1.5):
    events, arc_series = [], {}
    for idx, arc in arcs.items():
        s = OpenMeteo(mode="archive").hourly(
            arc["points"], start=f"{year}-{SEASON[0]}", end=f"{year}-{SEASON[1]}")
        hourly = [x["hourly"] for x in s]
        time.sleep(pause)                      # be polite to a free API

        pp = [daily_features(h) for h in hourly]
        dates = sorted(set.intersection(*[set(p) for p in pp]))
        res, daily = Reservoir(), {}
        for i, d in enumerate(dates):
            if i == 0:
                continue
            ss = [score_day(p[d], p[dates[i - 1]], arc["mean_lat"], d, res.level) for p in pp]
            daily[d] = {"index": round(mean(x["index"] for x in ss), 1),
                        "raw": round(mean(x["raw"] for x in ss), 1),
                        "gate": round(ss[0]["gate"], 3)}
            res.debit(daily[d]["raw"] * daily[d]["gate"])
        arc_series[idx] = daily

        for ev in arc_passages_season(hourly):
            win = [(ev["when"].date() + timedelta(days=k)).isoformat() for k in (0, 1)]
            ev.update(arc=idx, dist_mi=arc["dist_mi"], mean_lat=arc["mean_lat"],
                      index=max(daily.get(w, {}).get("index", 0.0) for w in win))
            events.append(ev)

    fronts = []
    for n, fr in enumerate(cluster_fronts(events), 1):
        spd = front_speed_mph(fr)
        fronts.append({"id": n, "arcs": [e["arc"] for e in fr], "speed_mph": spd,
                       "start": fr[0]["when"].isoformat(timespec="minutes"),
                       "peak_index": round(max(e["index"] for e in fr), 1),
                       "n_arcs": len(fr)})
    # Store the raw passage events too: arrival forecasting is a
    # superposition over per-arc departures, which the front summary alone
    # cannot reconstruct.
    return {"year": year, "fronts": fronts,
            "events": [{"arc": e["arc"], "dist_mi": e["dist_mi"],
                        "mean_lat": e["mean_lat"], "index": e["index"],
                        "strength": e["strength"], "points_firing": e["points_firing"],
                        "when": e["when"].isoformat(timespec="minutes")} for e in events],
            "arc_scores": {str(i): v for i, v in arc_series.items()}}


def main():
    years = [int(a) for a in sys.argv[1:]] or list(range(2015, 2026))
    os.makedirs(OUT, exist_ok=True)
    arcs = arc_points()
    for y in years:
        path = f"{OUT}/{y}.json"
        if os.path.exists(path):
            print(f"{y}: cached")
            continue
        r = season(y, arcs)
        with open(path, "w") as f:
            json.dump(r, f, indent=1, sort_keys=True)
        spds = [x["speed_mph"] for x in r["fronts"] if x["speed_mph"]]
        multi = [x for x in r["fronts"] if x["n_arcs"] >= 2]
        print(f"{y}: {len(r['fronts']):>3} fronts, {len(multi):>3} multi-arc, "
              f"{len(spds):>3} with speed"
              + (f", median {median(spds):.1f} mph" if spds else ""))


main()
