#!/usr/bin/env python3
"""Give new lattice nodes the weeks of past weather the model needs.

ECMWF open data keeps four days, so a node first seen today has four days of
history. The model needs more: the reservoir replays the season's depletion,
and the flight sim needs wind along every day a flock has been in the air.
Without it a new region looks like a full, untouched north.

Open-Meteo still serves past weather from the same model (ecmwf_ifs025), and
since the daily build moved to ECMWF files (D23) its free quota is idle. This
spends a fixed slice of it each morning on the nodes that lack history,
published flyway first, until every node is filled. Runs before
build_sites.py; never fatal.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

from dove.flyway import catalogue, PUBLISH_FLYWAYS
from dove.geo import arc_points
from dove.grid import PointCache, snap, CACHE_KEEP_DAYS
from dove.regions import FLYWAY_STATES

CACHE_DIR = "data/wxcache"
WANT_DAYS = 21                 # a full 16-day flight plus margin; the reservoir takes what exists
PAST_DAYS = CACHE_KEEP_DAYS    # fetch the whole kept window in one go
BUDGET = int(os.environ.get("BACKFILL_BUDGET", "12000"))    # location-days a morning
CHUNK = 100


def history_days(pt):
    p = os.path.join(CACHE_DIR, f"{pt[0]}_{pt[1]}.json")
    if not os.path.exists(p):
        return 0
    today = date.today().isoformat()
    return sum(1 for d in json.load(open(p)).get("features", {}) if d < today)


def nodes_for(sites):
    pts = {snap(*p) for s in sites for b in arc_points((s["lat"], s["lon"])).values()
           for p in b["points"]}
    return pts | {snap(s["lat"], s["lon"]) for s in sites}


def main():
    every = catalogue(flyways=list(FLYWAY_STATES))
    pub = nodes_for([s for s in every if s["flyway"] in PUBLISH_FLYWAYS])
    rest = nodes_for(every) - pub
    need = ([p for p in sorted(pub) if history_days(p) < WANT_DAYS] +
            [p for p in sorted(rest) if history_days(p) < WANT_DAYS])
    print(f"{len(need)} nodes short of {WANT_DAYS} days of history "
          f"({sum(1 for p in need if p in pub)} in the published flyway)")
    per_node = PAST_DAYS + 1
    take = need[:max(0, BUDGET // per_node)]
    done = 0
    for i in range(0, len(take), CHUNK):
        chunk = take[i:i + CHUNK]
        c = PointCache(past_days=PAST_DAYS, forecast_days=1, cache_dir=CACHE_DIR,
                       source="open-meteo")
        c.load(chunk)
        done += c.points
        if c.failed:
            print(f"  stopped: Open-Meteo refused a batch after {done} nodes")
            break
        time.sleep(20)                 # stay well under the per-minute limit
    left = len(need) - done
    print(f"  backfilled {done} nodes (~{done * per_node} location-days); {left} still short"
          + (f", ~{-(-left * per_node // BUDGET)} more mornings" if left else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
