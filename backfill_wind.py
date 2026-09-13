#!/usr/bin/env python3
"""One-time backfill of the season's wind, so the animation can span months.

Past weather never changes, so every day fetched here is fetched ONCE and
kept forever in data/wxcache. After this the timeline grows on its own: each
morning's build adds a day and never re-reads the history.

Paced and resumable. Open-Meteo bills by location-days, so the whole season
across every lattice node is more than a day's quota - run it across a couple
of evenings and it converges.
"""
import sys, time
from datetime import date
from dove.flyway_nodes import lattice_nodes
from dove.grid import PointCache

CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 120     # nodes per run
PAST = int(sys.argv[2]) if len(sys.argv) > 2 else 45       # days of history

def main():
    nodes = lattice_nodes()
    cache = PointCache(past_days=PAST, forecast_days=1, cache_dir="data/wxcache")
    have, need = [], []
    for pt in nodes:
        f, _ = cache._load_disk(pt)
        (have if len(f) >= PAST - 4 else need).append(pt)
    print(f"{len(nodes)} lattice nodes: {len(have)} already deep, {len(need)} need history")
    if not need:
        print("nothing to do — the whole lattice has the season")
        return
    todo = need[:CHUNK]
    print(f"fetching {len(todo)} nodes x {PAST} days = {len(todo)*PAST:,} location-days")
    t0 = time.time()
    try:
        cache.load(todo, progress=lambda d, n, r: print(f"  {d}/{n} ({r} req)", flush=True))
    except Exception as ex:
        print(f"stopped: {type(ex).__name__} — rerun later, progress is on disk")
    print(f"done in {time.time()-t0:.0f}s; {len(need)-len(todo)} nodes still shallow")

if __name__ == "__main__":
    main()
