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

# Where we PUBLISH forecasts. Deliberately smaller than what we WATCH:
# every band still reaches 155-621 mi north of each site, so the upstream
# system - fronts crossing Kansas and Nebraska, and the reservoir draining
# across the whole flyway - is modelled exactly as before. Shrinking this set
# only shrinks how many places can look up a forecast, and buys quota headroom.
# Add a state here to extend coverage; nothing else changes.
SITE_STATES = {"TX", "OK"}

# Central Management Unit states. Rough bounding boxes - good enough to decide
# whether to forecast a grid point, which is all they are used for.
STATE_BBOX = {
    "TX": (25.8, 36.5, -106.7, -93.5),
    "OK": (33.6, 37.0, -103.0, -94.4),
    "KS": (36.99, 40.0, -102.1, -94.6),
    "NE": (40.0, 43.0, -104.1, -95.3),
    "NM": (31.3, 37.0, -104.0, -103.0),   # eastern plains only
    "CO": (37.0, 41.0, -104.0, -102.0),   # eastern plains only
    "MO": (36.0, 40.6, -95.8, -89.1),
    "AR": (33.0, 36.5, -94.6, -89.6),
    "LA": (28.9, 33.0, -94.0, -88.8),
}

# Crude water exclusions, so the map does not show dots in the Gulf.
def _on_water(lat, lon):
    if lat < 29.6 and lon > -94.0:              # Gulf east of the Texas coast
        return True
    if lat < 27.0 and lon > -97.2:              # lower Laguna Madre / Gulf
        return True
    if lat < 26.4 and lon < -98.6:              # south of the Rio Grande
        return True
    return False


def state_of(lat, lon):
    """Which state a grid point sits in — INTERNAL USE ONLY.

    Never display this. Bounding boxes cannot separate the Texas panhandle
    from Oklahoma (the panhandle sits entirely inside OK's box), so a point
    near a border is often mislabelled. It is only used to decide which grid
    points are worth computing. The name a hunter sees comes from their own
    search, where the geocoder supplies the correct state.
    """
    hits = [s for s, (a, b, c, d) in STATE_BBOX.items() if a <= lat <= b and c <= lon <= d]
    if not hits:
        return None
    # overlapping boxes: prefer the one whose centre is nearest
    return min(hits, key=lambda s: (lambda a, b, c, d: (lat - (a + b) / 2) ** 2
                                    + (lon - (c + d) / 2) ** 2)(*STATE_BBOX[s]))


def site_id(lat, lon):
    """Stable across runs: lattice indices, not a hash of the name."""
    return f"r{round(lat / LAT_STEP):03d}c{round(lon / LON_STEP_LOC):+04d}"


def catalogue(states=None):
    """Every grid point we publish a forecast for."""
    boxes = {k: v for k, v in STATE_BBOX.items() if k in (states or SITE_STATES)}
    lo_lat = min(b[0] for b in boxes.values())
    hi_lat = max(b[1] for b in boxes.values())
    lo_lon = min(b[2] for b in boxes.values())
    hi_lon = max(b[3] for b in boxes.values())

    out, lat = [], snap_lat(lo_lat)
    while lat <= hi_lat:
        lon = round(round(lo_lon / LON_STEP_LOC) * LON_STEP_LOC, 4)
        while lon <= hi_lon:
            st = state_of(lat, lon)
            if st in boxes and not _on_water(lat, lon):
                out.append({"id": site_id(lat, lon), "lat": round(lat, 4),
                            "lon": round(lon, 4), "state": st})
            lon = round(lon + LON_STEP_LOC, 4)
        lat = round(lat + LAT_STEP, 4)
    return out


def nearest(lat, lon, sites):
    return min(sites, key=lambda s: (s["lat"] - lat) ** 2
               + ((s["lon"] - lon) * math.cos(math.radians(lat))) ** 2)
