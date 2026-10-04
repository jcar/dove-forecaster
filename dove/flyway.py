"""Which places we forecast for, and how a hunter's town maps onto one.

Locations sit on the same 0.75 deg rows as the weather lattice, so every
band latitude is an exact lattice row (see grid.py). Longitude spacing is
also 0.75 deg, which is ~45 mi at these latitudes - well inside the model's
own resolution, since the bands it reads are 150-620 mi away and 420 mi wide.
"""
import math

from .grid import LAT_STEP, LON_STEP, snap_lat

# Locations sit ON the weather lattice, not beside it. That way each
# location IS a node: the model-critical part of its own series (the detected
# front arrival, and the southern end of the wind field) comes free from the
# band fetch instead of costing a second request for every site.
LON_STEP_LOC = LON_STEP

# Where we PUBLISH forecasts: the Central Flyway (2026-10-04, D24). Every
# band still reaches 155-621 mi north of each site, into Canada for the
# northern tier. The other three flyways are BUILT every day in shadow -
# forecast, saved, graded against eBird - but not published until the counts
# say they work. Membership comes from real state outlines (dove/regions.py);
# the old bounding boxes put the Texas panhandle in Oklahoma and a site in
# Chihuahua.
from .regions import state_at, FLYWAY_OF, FLYWAY_STATES

PUBLISH_FLYWAYS = {"central"}
SITE_STATES = {s for f in PUBLISH_FLYWAYS for s in FLYWAY_STATES[f]}
LOWER48 = (24.5, 49.4, -125.0, -66.9)


def state_of(lat, lon):
    """Two-letter state under a grid point, from the real outline."""
    return state_at(lat, lon)


def site_id(lat, lon):
    """Stable across runs: lattice indices, not a hash of the name."""
    return f"r{round(lat / LAT_STEP):03d}c{round(lon / LON_STEP_LOC):+04d}"


def catalogue(states=None, flyways=None):
    """Every grid point we forecast for: those in `states`, or in `flyways`,
    defaulting to the published set."""
    if flyways is not None:
        states = {s for f in flyways for s in FLYWAY_STATES[f]}
    states = states or SITE_STATES
    out, lat = [], snap_lat(LOWER48[0])
    while lat <= LOWER48[1]:
        lon = round(round(LOWER48[2] / LON_STEP_LOC) * LON_STEP_LOC, 4)
        while lon <= LOWER48[3]:
            st = state_at(lat, lon)
            if st in states:
                out.append({"id": site_id(lat, lon), "lat": round(lat, 4),
                            "lon": round(lon, 4), "state": st,
                            "flyway": FLYWAY_OF.get(st)})
            lon = round(lon + LON_STEP_LOC, 4)
        lat = round(lat + LAT_STEP, 4)
    return out


def nearest(lat, lon, sites):
    return min(sites, key=lambda s: (s["lat"] - lat) ** 2
               + ((s["lon"] - lon) * math.cos(math.radians(lat))) ** 2)
