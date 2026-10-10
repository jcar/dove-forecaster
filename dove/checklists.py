"""Effort-corrected eBird counts: whole checklists, not sightings (D33).

The wave (dove/wave.py) counts SIGHTINGS: a birder who looked for an hour and
saw no doves leaves no trace in it, so a busy birding day looks like a dove
day. The 2026-10-10 hindcast showed it - the non-migrant control moved with
the mourning dove at every lag. A checklist knows how long its birder looked
and, when complete, that every bird seen was reported, so an absent species
is a real zero. Birds per hour of complete checklists measures birds.

Each morning (daily.py, after the forecast and the wave) this pulls the checklists of ONE settled day (LAG_DAYS back;
most are submitted within two days) for every county touching a Central
sample circle, keeps those inside a circle, and fetches each list's detail.
One checklist gives every tracked species at once - doves, ducks and the
control - with its zeros.

Stored without birder names, checklist IDs or coordinates: a row is a circle,
the effort and the counts of the tracked species. Raw eBird data is not
republished (eBird terms; and personal locations are people's yards).
"""
import json
import os
import random
import time
from datetime import date, timedelta

from .ebird import _get, ALL_SPECIES
from .wave import circles, _km, RADIUS_KM

OUT = "data/checklists"
COUNTY_MAP = "data/geo/checklist_counties.json"
LAG_DAYS = 3                # the day pulled: settled, most lists submitted
FILL_BACK = 7               # also fill any missing day this far back
PER_CIRCLE = 20             # detail fetches per circle per day (random sample)
BUDGET_S = 6 * 60           # never hold up the morning build
FLYWAYS = ("central",)


def county_map(flyways=FLYWAYS, refresh=False):
    """circle -> eBird county codes, from the hotspots within the circle
    (one call per circle, cached in the repo). Counties with no hotspot near
    a circle have next to no checklists there."""
    if os.path.exists(COUNTY_MAP) and not refresh:
        return json.load(open(COUNTY_MAP))
    from .regions import nearest_flyway
    out = {}
    for name, lat, lon in circles():
        if nearest_flyway(lat, lon) not in flyways:
            continue
        hs = _get("ref/hotspot/geo", lat=lat, lng=lon, dist=RADIUS_KM, fmt="json")
        out[name] = {"lat": lat, "lon": lon,
                     "counties": sorted({h["subnational2Code"] for h in hs if h.get("subnational2Code")})}
    os.makedirs(os.path.dirname(COUNTY_MAP), exist_ok=True)
    json.dump(out, open(COUNTY_MAP, "w"), indent=1, sort_keys=True)
    return out


def _row(circle, c):
    """One checklist, reduced to what scoring needs."""
    counts = {}
    for o in c.get("obs", []):
        sp = o.get("speciesCode")
        if sp in ALL_SPECIES:
            n = o.get("howManyAtleast")
            counts[sp] = "X" if n is None else int(n)      # X = present, not counted
    return {"c": circle, "proto": c.get("protocolId"), "all": bool(c.get("allObsReported")),
            "hrs": c.get("durationHrs"), "km": c.get("effortDistanceKm"),
            "obs": c.get("numObservers"), "hour": int(c["obsDt"][11:13]) if len(c.get("obsDt", "")) >= 13 else None,
            "n": counts}


def collect_day(d, cmap=None, deadline=None):
    """Every circle's checklists for date `d`. Returns the day's record."""
    cmap = cmap or county_map()
    rng = random.Random(d.isoformat())                    # reproducible sample
    by_circle, listed = {}, {}
    counties = sorted({k for v in cmap.values() for k in v["counties"]})
    seen = set()
    for co in counties:
        if deadline and time.time() > deadline:
            return None
        for L in _get(f"product/lists/{co}/{d.year}/{d.month}/{d.day}", maxResults=200):
            loc = L.get("loc") or {}
            la, lo = loc.get("lat"), loc.get("lng")
            if la is None or lo is None:
                continue
            # a shared (group) checklist is one outing filed once per birder
            key = (L.get("locId"), L.get("obsDt"), L.get("obsTime"))
            if key in seen:
                continue
            seen.add(key)
            for cname, v in cmap.items():
                if co in v["counties"] and _km(la, lo, v["lat"], v["lon"]) <= RADIUS_KM:
                    by_circle.setdefault(cname, []).append(L["subId"])
                    break
    rows = []
    for cname, subs in sorted(by_circle.items()):
        listed[cname] = len(subs)
        for sub in (subs if len(subs) <= PER_CIRCLE else rng.sample(subs, PER_CIRCLE)):
            if deadline and time.time() > deadline:
                return None
            try:
                rows.append(_row(cname, _get(f"product/checklist/view/{sub}")))
            except Exception as ex:
                print(f"  checklists {sub}: skipped ({type(ex).__name__})")
    return {"date": d.isoformat(), "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "per_circle_cap": PER_CIRCLE, "listed": listed, "rows": rows}


def run(today=None, budget_s=BUDGET_S):
    """The settled day, plus any missing day within FILL_BACK. Never fatal."""
    today = today or date.today()
    os.makedirs(OUT, exist_ok=True)
    deadline = time.time() + budget_s
    try:
        cmap = county_map()
    except Exception as ex:
        print(f"  checklists: no county map ({type(ex).__name__})")
        return 0
    done = 0
    for back in range(LAG_DAYS, FILL_BACK + 1):
        d = today - timedelta(days=back)
        path = f"{OUT}/{d.isoformat()}.json"
        if os.path.exists(path):
            continue
        rec = collect_day(d, cmap, deadline)
        if rec is None:
            print(f"  checklists: time budget hit on {d}; it is retried tomorrow")
            break
        json.dump(rec, open(path, "w"), separators=(",", ":"))
        done += 1
        comp = sum(1 for r in rec["rows"] if r["all"] and r["hrs"])
        print(f"  checklists {d}: {sum(rec['listed'].values())} listed in {len(rec['listed'])} circles, "
              f"{len(rec['rows'])} read, {comp} complete with effort")
    return done


def rates(rows, species, max_hrs=5.0):
    """Birds per hour on complete, timed, stationary/traveling checklists, and
    how many such lists - for one circle-window's rows. Lists reporting a
    species as X (present, uncounted) are dropped for that species: their
    count is unknown, not zero."""
    use = [r for r in rows if r["all"] and r["hrs"] and 0 < r["hrs"] <= max_hrs
           and r["proto"] in ("P21", "P22")]
    birds = hrs = 0.0
    n = 0
    for r in use:
        vals = [r["n"].get(s, 0) for s in species]
        if any(v == "X" for v in vals):
            continue
        birds += sum(vals)
        hrs += r["hrs"]
        n += 1
    return (birds / hrs if hrs else None), n
