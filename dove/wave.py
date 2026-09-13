"""Flyway-wide dove density — the southward wave.

A single county's count going up is weak evidence: observer noise fakes it
easily. The strong question is whether the increase MOVES SOUTH over days,
band by band, in the order and at the speed our fronts predict. Birders in
Nebraska and birders in Texas do not coordinate their weekends, so a
propagating anomaly is migration or it is nothing.

Cheap by design: one call returns every recent sighting of a species within
a radius, so we never walk checklists. Three circles per band, four bands
plus the fields.

We store RAW counts, never a derived index. The right normalisation is not
settled, and storing raw means we can revise it later without re-fetching a
season we can never get back.
"""
import json
import os
from collections import defaultdict

from .ebird import SPECIES, _get
from .geo import arc_points, HOME, FLYWAY_W, FLYWAY_E

CACHE = "data/wave"
RADIUS_KM = 50          # eBird's maximum for a geo query
CIRCLES_PER_BAND = 3
LOOKBACK_DAYS = 7       # overlap between runs, so a missed morning self-heals


def circles():
    """Sample points: three across each band, plus the fields themselves."""
    out = [("home", HOME[0], HOME[1])]
    for idx, a in arc_points().items():
        lat = a["mean_lat"]
        for k, off in enumerate((-3.0, 0.0, 3.0)):
            lon = min(max(HOME[1] + off, FLYWAY_W), FLYWAY_E)
            out.append((f"band{idx}_{k}", round(lat, 4), round(lon, 4)))
    return out


def collect(back=LOOKBACK_DAYS):
    """Raw dove counts by sample circle, species and observation date."""
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {"birds": 0, "locations": 0, "counted": 0})))
    for name, lat, lon in circles():
        for sp in SPECIES:
            try:
                obs = _get(f"data/obs/geo/recent/{sp}", lat=lat, lng=lon,
                           dist=RADIUS_KM, back=back)
            except Exception as ex:
                print(f"  wave {name}/{sp}: skipped ({type(ex).__name__})")
                continue
            for o in obs:
                d = o["obsDt"][:10]
                cell = data[name][sp][d]
                cell["locations"] += 1
                n = o.get("howMany")
                if n is not None:
                    cell["birds"] += int(n)
                    cell["counted"] += 1
    return data


def snapshot(run_date):
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{run_date}.json"
    raw = collect()
    out = {"run_date": run_date, "radius_km": RADIUS_KM,
           "circles": {n: {"lat": la, "lon": lo} for n, la, lo in circles()},
           "counts": {n: {s: dict(v) for s, v in sp.items()} for n, sp in raw.items()}}
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out
