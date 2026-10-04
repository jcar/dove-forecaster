"""Flyway-wide dove density — the southward wave.

A single county's count going up is weak evidence: observer noise fakes it
easily. The strong question is whether the increase MOVES SOUTH over days,
band by band, in the order and at the speed our fronts predict. Birders in
Nebraska and birders in Texas do not coordinate their weekends, so a
propagating anomaly is migration or it is nothing.

Cheap by design: one call returns every recent sighting of a species within
a radius, so we never walk checklists. Three circles per band, four bands
plus the fields.
Nationwide that is ~130 circles x 3 species, a few minutes of polite calls.

We store RAW counts, never a derived index. The right normalisation is not
settled, and storing raw means we can revise it later without re-fetching a
season we can never get back.
"""
import json
import os
from collections import defaultdict

from .ebird import SPECIES, ALL_SPECIES, _get

CACHE = "data/wave"
RADIUS_KM = 50          # eBird's maximum for a geo query
LOOKBACK_DAYS = 7       # overlap between runs, so a missed morning self-heals
BUDGET_S = 15 * 60      # stop pulling after this long; see collect()

# ABSOLUTE coordinates, deliberately. These were once named band1_0, band2_1...
# derived from one hunter's position — which meant that the day the anchor
# moved, "band1_0" in an old file and a new file would be different ground and
# the accumulated history would be silently unjoinable. The wave measures a
# continental phenomenon; it must be pinned to the continent, not to a user.
# 2.5 deg rows, 3 deg columns, on the SAME lattice the original 21 circles sat
# on, so their names - and three weeks of history - carry over unchanged.
# Extended 2026-10-04 from three plains columns to the lower 48: every flyway
# is watched, including ones we do not yet publish forecasts for, because
# their counts are the only way those forecasts can ever be graded.
ROWS = [26.0, 28.5, 31.0, 33.5, 36.0, 38.5, 41.0, 43.5, 46.0, 48.5]
COLS = [-123.5 + 3.0 * k for k in range(19)]          # -123.5 ... -69.5
# The top two rows were added 2026-09-25, the national grid 2026-10-04; each
# circle's history starts the day it was added.


def circles():
    """Fixed lattice across the lower 48, named by where it is on the ground.
    Kept only where the centre is in (or within ~50 mi of) a US state: a
    circle in the open Gulf or deep in Canada has no birders to count."""
    from .regions import nearest_flyway
    return [(f"r{lat}_c{lon}", lat, lon) for lat in ROWS for lon in COLS
            if nearest_flyway(lat, lon) is not None]


# The lower 48 (and DC) by eBird region code. One call per STATE per species
# returns every birding spot in the state - one record per spot, its latest
# sighting - with coordinates. Binning those into the circles ourselves gives
# exactly what a 50 km geo call gives, for 48 calls a species instead of 128,
# and is what made adding six duck species affordable (D25).
STATES = ["AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "ID", "IL", "IN",
          "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
          "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
          "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
# Border circles reach into Canada and Mexico; their history (from 50 km geo
# calls) includes those spots, so leaving them out would put a step in it.
# One country-wide call each covers them.
REGIONS = [f"US-{s}" for s in STATES] + ["CA", "MX"]


def _km(la1, lo1, la2, lo2):
    import math
    p1, p2 = math.radians(la1), math.radians(la2)
    h = (math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2)
         * math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(h))


def _binner():
    """record (lat, lon) -> the circle it falls in, or None. Circles are
    >200 km apart, so a spot is in at most one."""
    cs = circles()
    def which(lat, lon):
        for name, cla, clo in cs:
            if abs(lat - cla) <= 0.46 and abs(lon - clo) <= 0.75 and \
                    _km(lat, lon, cla, clo) <= RADIUS_KM:
                return name
        return None
    return which


def collect(back=LOOKBACK_DAYS, species=None, regions=None):
    """Raw counts by sample circle, species and observation date, plus the
    per-location records they were summed from.

    eBird returns ONE record per location - its most recent sighting. A
    hotspot birded on Monday and again on Wednesday shows only Wednesday, so
    Monday's count in Wednesday's pull is short. Aggregates alone cannot be
    repaired after the fact; the records can be unioned across overlapping
    pulls, which is why they are kept (2026-10-04).
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {"birds": 0, "locations": 0, "counted": 0})))
    records = defaultdict(lambda: defaultdict(list))
    which = _binner()
    seen = set()                     # a spot belongs to one region, but be safe
    # Species-major, doves first: if the time budget is hit, the published
    # forecast's species are already complete everywhere.
    jobs = [(reg, sp) for sp in (species or ALL_SPECIES) for reg in (regions or REGIONS)]

    def fetch(job):
        reg, sp = job
        try:
            return job, _get(f"data/obs/{reg}/recent/{sp}", back=back, maxResults=10000)
        except Exception as ex:
            print(f"  wave {reg}/{sp}: skipped ({type(ex).__name__})")
            return job, []

    # One at a time, deliberately. Four concurrent requests on top of a day of
    # testing drew HTTP 429 (Retry-After ~6 s) on 2026-10-04. eBird publishes
    # no limit; serial with _get's adaptive pause is the polite pace, and at
    # normal latency (~0.3-1.5 s) the morning's 459 calls take 3-10 minutes.
    import time as _t
    t0, results = _t.time(), []
    for j in jobs:
        # A throttled key makes every call wait out its retries; without a
        # cap the morning job could run for hours. Keep what we have.
        if _t.time() - t0 > BUDGET_S:
            print(f"  wave: time budget hit after {len(results)}/{len(jobs)} calls; "
                  f"the rest self-heal from tomorrow's 7-day look-back")
            break
        results.append(fetch(j))
    for (reg, sp), obs in results:
            for o in obs:
                if "lat" not in o or "lng" not in o:
                    continue
                name = which(o["lat"], o["lng"])
                key = (o.get("locId"), sp)
                if name is None or key in seen:
                    continue
                seen.add(key)
                d = o["obsDt"][:10]
                records[name][sp].append([o.get("locId"), d, o.get("howMany")])
                cell = data[name][sp][d]
                cell["locations"] += 1
                n = o.get("howMany")
                if n is not None:
                    cell["birds"] += int(n)
                    cell["counted"] += 1
    return data, records


def snapshot(run_date):
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{run_date}.json"
    raw, records = collect()
    out = {"run_date": run_date, "radius_km": RADIUS_KM,
           "circles": {n: {"lat": la, "lon": lo} for n, la, lo in circles()},
           "counts": {n: {s: dict(v) for s, v in sp.items()} for n, sp in raw.items()},
           "records": {n: dict(sp) for n, sp in records.items()}}
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)   # 9 species: keep it compact
    return out
