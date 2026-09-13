#!/usr/bin/env python3
"""Build a forecast for every location in the flyway, from shared fetches.

The whole design is that weather is fetched ONCE for the region, not once
per location. Per-location work is then pure arithmetic.
"""
import json, os, sys, time
from dove.flyway import catalogue
from dove.geo import arc_points
from dove.grid import PointCache, snap, BATCH
from dove.weather import OpenMeteo
from dove.local import LOCAL_HOURLY, LOCAL_DAILY
from dove.engine import run, season_past_days

OUT = "docs/data"
DISPLAY_DAYS = 14


def slim(res, site):
    """What the page needs, and nothing else. ~4 KB instead of ~26 KB."""
    return {
        "id": site["id"], "lat": site["lat"], "lon": site["lon"],
        "generated_at": res["generated_at"],
        "arcs": {k: {kk: v[kk] for kk in ("label", "north_mi", "mean_lat", "usable")}
                 for k, v in res["arcs"].items()},
        "arrival": res["arrival"], "still_airborne": res["still_airborne"],
        "fronts": [{k: f.get(k) for k in ("id", "arcs", "speed_mph", "reaches_home",
                                          "actual_speed_mph", "confidence", "passages")}
                   for f in res["fronts"]],
        # heatmap needs only what its tooltip shows
        "scores": {b: {d: [v["index"], v.get("obs", {}).get("push_mph"),
                           v.get("obs", {}).get("temp_drop")]
                       for d, v in sorted(s.items())[-DISPLAY_DAYS:]}
                   for b, s in res["arc_scores"].items()},
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    sites = catalogue()[:limit]
    t0 = time.time()

    # location points go in the SAME lattice fetch - each site is a node
    band_pts = {snap(*p) for s in sites
                for b in arc_points((s["lat"], s["lon"])).values() for p in b["points"]}
    band_pts |= {snap(s["lat"], s["lon"]) for s in sites}
    print(f"{len(sites)} locations, {len(band_pts)} unique lattice nodes")

    # past_days is small because the disk cache carries the season's history;
    # only one new past day plus the forecast window is actually fetched.
    cache = PointCache(past_days=2, cache_dir="data/wxcache")
    cache.load(band_pts, progress=lambda d, t, r: print(f"  bands {d}/{t} ({r} req)", flush=True))

    lreq = 0          # locations are lattice nodes now; no separate fetch

    os.makedirs(f"{OUT}/loc", exist_ok=True)
    index, built, failed = [], 0, 0
    for s in sites:
        try:
            res = run((s["lat"], s["lon"]), s["id"], grid=cache, ensemble=None)
        except Exception as ex:
            failed += 1
            continue
        json.dump(slim(res, s), open(f"{OUT}/loc/{s['id']}.json", "w"),
                  separators=(",", ":"))
        peak = max(res["arrival"], key=lambda r: r["arrival"])
        index.append({"id": s["id"], "lat": s["lat"], "lon": s["lon"],
                      "peak_date": peak["date"], "peak": peak["arrival"],
                      "bands": [res["arcs"][k]["label"] for k in sorted(res["arcs"])]})
        built += 1
    json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "sites": index}, open(f"{OUT}/index.json", "w"), separators=(",", ":"))

    sz = sum(os.path.getsize(f"{OUT}/loc/{s['id']}.json") for s in sites
             if os.path.exists(f"{OUT}/loc/{s['id']}.json"))
    print(f"\n  built {built}, failed {failed}")
    print(f"  HTTP requests: {cache.requests} band + {lreq} local = {cache.requests + lreq}")
    print(f"  payload: {sz/1e6:.2f} MB total, {sz/max(built,1):.0f} B/location, "
          f"index {os.path.getsize(f'{OUT}/index.json')/1000:.0f} KB")
    print(f"  elapsed {time.time()-t0:.0f}s")


main()
