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

from .ebird import SPECIES, _get

CACHE = "data/wave"
RADIUS_KM = 50          # eBird's maximum for a geo query
LOOKBACK_DAYS = 7       # overlap between runs, so a missed morning self-heals

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


def collect(back=LOOKBACK_DAYS):
    """Raw dove counts by sample circle, species and observation date, plus
    the per-location records they were summed from.

    eBird's geo/recent returns ONE record per location - its most recent
    sighting. A hotspot birded on Monday and again on Wednesday shows only
    Wednesday, so Monday's count in Wednesday's pull is short. Aggregates
    alone cannot be repaired after the fact; the records can be unioned
    across overlapping pulls, which is why they are now kept (2026-10-04).
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {"birds": 0, "locations": 0, "counted": 0})))
    records = defaultdict(lambda: defaultdict(list))
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
        json.dump(out, f, indent=1, sort_keys=True)
    return out
