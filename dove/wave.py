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

CACHE = "data/wave"
RADIUS_KM = 50          # eBird's maximum for a geo query
LOOKBACK_DAYS = 7       # overlap between runs, so a missed morning self-heals

# ABSOLUTE coordinates, deliberately. These were once named band1_0, band2_1...
# derived from one hunter's position — which meant that the day the anchor
# moved, "band1_0" in an old file and a new file would be different ground and
# the accumulated history would be silently unjoinable. The wave measures a
# continental phenomenon; it must be pinned to the continent, not to a user.
ROWS = [33.5, 36.0, 38.5, 41.0, 43.5]      # N Texas -> the Dakotas
COLS = [-99.5, -96.5, -93.5]               # west / centre / east of the flyway


def circles():
    """Fixed lattice across the flyway, named by where it is on the ground."""
    return [(f"r{lat}_c{lon}", lat, lon) for lat in ROWS for lon in COLS]


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
