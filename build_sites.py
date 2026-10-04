#!/usr/bin/env python3
"""Build a forecast for every location in the flyway, from shared fetches.

The whole design is that weather is fetched ONCE for the region, not once
per location. Per-location work is then pure arithmetic.
"""
import json, os, sys, time
from dove.flyway import catalogue, PUBLISH_FLYWAYS
from dove.regions import FLYWAY_STATES
from dove.geo import arc_points
from dove.grid import PointCache, snap, BATCH
from dove.weather import OpenMeteo
from dove.local import LOCAL_HOURLY, LOCAL_DAILY
from dove.engine import run, season_past_days
import flyway
from dove.regions import nearest_flyway

US_FIT = flyway.albers_box_fit_us()

OUT = "docs/data"
DISPLAY_DAYS = 14
FLOW_DAYS = 30          # ~2 weeks back plus the forecast, for the animation


def history_days(cache, site):
    """Fewest past days of weather held by any node this site reads. New
    nodes start with ECMWF's four; backfill_history.py fills them over a few
    mornings, and the page says so until it has (WARM_DAYS)."""
    today = time.strftime("%Y-%m-%d")
    pts = [snap(*p) for b in arc_points((site["lat"], site["lon"])).values() for p in b["points"]]
    pts.append(snap(site["lat"], site["lon"]))
    return min(sum(1 for d in (cache.features(*p) or {}) if d < today) for p in pts)


def slim(res, site, hist=None):
    """What the page needs, and nothing else. ~4 KB instead of ~26 KB."""
    return {
        "id": site["id"], "lat": site["lat"], "lon": site["lon"],
        "flyway": nearest_flyway(site["lat"], site["lon"]) or "central",
        "history_days": hist,
        "us_xy": list(US_FIT(site["lat"], site["lon"])),     # on the national bird map
        "generated_at": res["generated_at"],
        "arcs": {k: {kk: v[kk] for kk in ("label", "north_mi", "mean_lat", "usable")}
                 for k, v in res["arcs"].items()},
        "arrival": res["arrival"], "still_airborne": res["still_airborne"],
        "fronts": [{k: f.get(k) for k in ("id", "arcs", "skipped_bands", "speed_mph",
                                          "reaches_home", "actual_speed_mph",
                                          "confidence", "passages")}
                   for f in res["fronts"]],
        # heatmap needs only what its tooltip shows
        "scores": {b: {d: [v["index"], v.get("obs", {}).get("push_mph"),
                           v.get("obs", {}).get("temp_drop")]
                       for d, v in sorted(s.items())[-DISPLAY_DAYS:]}
                   for b, s in res["arc_scores"].items()},
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    # Every flyway is FORECAST; only PUBLISH_FLYWAYS are published. The rest
    # are saved to data/shadow/ so their calls can be graded against eBird
    # before anyone sees them (D24). With ECMWF open data the extra flyways
    # cost compute, not quota.
    every = catalogue(flyways=list(FLYWAY_STATES))[:limit]
    sites = [s for s in every if s["flyway"] in PUBLISH_FLYWAYS]
    shadow = [s for s in every if s["flyway"] not in PUBLISH_FLYWAYS]
    t0 = time.time()

    # location points go in the SAME lattice fetch - each site is a node
    band_pts = {snap(*p) for s in every
                for b in arc_points((s["lat"], s["lon"])).values() for p in b["points"]}
    band_pts |= {snap(s["lat"], s["lon"]) for s in every}
    print(f"{len(sites)} published + {len(shadow)} shadow locations, "
          f"{len(band_pts)} unique lattice nodes")

    # past_days is small because the disk cache carries the season's history;
    # only one new past day plus the forecast window is actually fetched.
    # ECMWF open data first: one download covers every node at no per-point
    # cost (D23). Open-Meteo - same model, metered - fills whatever it missed.
    cache = PointCache(past_days=2, cache_dir="data/wxcache",
                       source=os.environ.get("WX_SOURCE", "ecmwf"))
    cache.load(band_pts, progress=lambda d, t, r: print(f"  bands {d}/{t} ({r} req)", flush=True))
    missing = [p for p in band_pts if not cache.covers([p])]
    # Open-Meteo's free tier cannot carry the whole country; spend it on the
    # published flyway's nodes only.
    pub_pts = {snap(*p) for s in sites
               for b in arc_points((s["lat"], s["lon"])).values() for p in b["points"]}
    pub_pts |= {snap(s["lat"], s["lon"]) for s in sites}
    missing = [p for p in missing if p in pub_pts]
    if missing and cache.source != "open-meteo":
        print(f"  {len(missing)} nodes missing from ECMWF; falling back to Open-Meteo", flush=True)
        cache.source = "open-meteo"
        cache.load(missing)

    lreq = 0          # locations are lattice nodes now; no separate fetch

    os.makedirs(f"{OUT}/loc", exist_ok=True)
    for f in os.listdir(f"{OUT}/loc"):          # locations that left the catalogue
        if f[:-5] not in {s["id"] for s in sites}:
            os.remove(f"{OUT}/loc/{f}")
    index, built, failed = [], 0, 0
    log_rows, log_dates = {}, []

    def log_row(res, s):
        if not log_dates:
            log_dates.append([r["date"] for r in res["arrival"]])
        return {"lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"],
                "published": s["flyway"] in PUBLISH_FLYWAYS,
                "arrival": [round(r["arrival"]) for r in res["arrival"]],
                "challenger": [round(r["arrival"]) for r in res["arrival_challenger"]["days"]],
                "airborne": round(res["still_airborne"]),
                "history_days": history_days(cache, s)}

    for s in sites:
        try:
            res = run((s["lat"], s["lon"]), s["id"], grid=cache, ensemble=None)
        except Exception as ex:
            failed += 1
            continue
        json.dump(slim(res, s, history_days(cache, s)), open(f"{OUT}/loc/{s['id']}.json", "w"),
                  separators=(",", ":"))
        peak = max(res["arrival"], key=lambda r: r["arrival"])
        index.append({"id": s["id"], "lat": s["lat"], "lon": s["lon"],
                      "peak_date": peak["date"], "peak": peak["arrival"],
                      "bands": [res["arcs"][k]["label"] for k in sorted(res["arcs"])]})
        built += 1

        log_rows[s["id"]] = log_row(res, s)

    # Shadow flyways: the same forecast, never shown on the page. Every
    # location's call - published or not - goes into data/sitelog/, which is
    # what grade.py scores against eBird (D24).
    sfail = 0
    for s in shadow:
        try:
            res = run((s["lat"], s["lon"]), s["id"], grid=cache, ensemble=None)
        except Exception:
            sfail += 1
            continue
        log_rows[s["id"]] = log_row(res, s)
    rows = {k: v for k, v in log_rows.items() if not v["published"]}
    if log_rows:
        os.makedirs("data/sitelog", exist_ok=True)
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "dates": log_dates[0], "sites": log_rows},
                  open(f"data/sitelog/{time.strftime('%Y-%m-%d')}.json", "w"),
                  separators=(",", ":"))
    print(f"  shadow: {len(rows)} locations in {len({r['flyway'] for r in rows.values()})} "
          f"flyways, {sfail} failed")
    # Strength labels derived FROM THE DATA, not from constants I guessed.
    # The old cut-offs (4/14/30) were set when the index topped out near 50;
    # completing front detection pushed the median to 76, so every location
    # read "Big push" and the label stopped discriminating. Quartiles of the
    # live distribution keep it meaningful as the model changes.
    vals = sorted(e["peak"] for e in index if e["peak"] > 0.5)
    q = (lambda p: round(vals[int(len(vals) * p)], 1)) if vals else (lambda p: 0)
    scale = {"few": q(0.25), "decent": q(0.55), "big": q(0.82)} if vals else None

    json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "scale": scale, "sites": index},
              open(f"{OUT}/index.json", "w"), separators=(",", ":"))

    # the moving picture: ~30 days of the real 2D wind field plus each
    # location's arrivals, read from the cache we already loaded
    try:
        all_dates = sorted({d for f in cache._feat.values() for d in f})
        dates = all_dates[-FLOW_DAYS:]
        loaded = [json.load(open(f"{OUT}/loc/{s['id']}.json")) for s in sites
                  if os.path.exists(f"{OUT}/loc/{s['id']}.json")]
        fp, fsz = flyway.export(cache, loaded, dates)
        print(f"  flow: {fsz/1000:.0f} KB, {len(dates)} days "
              f"({dates[0]}..{dates[-1]}), {len(cache._feat)} wind nodes")
    except Exception as ex:
        print(f"  flow export skipped ({type(ex).__name__}: {ex})")

    sz = sum(os.path.getsize(f"{OUT}/loc/{s['id']}.json") for s in sites
             if os.path.exists(f"{OUT}/loc/{s['id']}.json"))
    print(f"\n  built {built}, failed {failed}")
    print(f"  HTTP requests: {cache.requests} band + {lreq} local = {cache.requests + lreq}")
    print(f"  payload: {sz/1e6:.2f} MB total, {sz/max(built,1):.0f} B/location, "
          f"index {os.path.getsize(f'{OUT}/index.json')/1000:.0f} KB")
    print(f"  elapsed {time.time()-t0:.0f}s")


# Guarded: importing this module must never start fetching weather.
if __name__ == "__main__":
    main()