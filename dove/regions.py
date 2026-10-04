"""Which state, and which flyway, a point is in - from real state outlines.

Replaces bounding boxes for every "where is this" decision. Boxes overlap
(the Texas panhandle sits inside Oklahoma's box) and spill into Mexico, the
Gulf and Canada; at one or two states that was tolerable, nationwide it is
not. The outlines are the public US-states GeoJSON already used to draw the
map, committed at data/geo/us-states.json so the daily build is self-contained.

Flyways are the four USFWS administrative flyways, assigned by whole state.
That is a simplification the birds do not observe - western Montana,
Wyoming, Colorado and New Mexico drain partly to the Pacific - but it is the
line hunters and state agencies use, and it is stable.
"""
import json
import os
from functools import lru_cache

SRC = os.path.join(os.path.dirname(__file__), "..", "data", "geo", "us-states.json")

ABBR = {
    "Alabama": "AL", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

FLYWAY_STATES = {
    "pacific": {"WA", "OR", "CA", "ID", "NV", "UT", "AZ"},
    "central": {"MT", "WY", "CO", "NM", "ND", "SD", "NE", "KS", "OK", "TX"},
    "mississippi": {"MN", "WI", "MI", "IA", "IL", "IN", "OH", "MO", "KY", "TN",
                    "AR", "MS", "AL", "LA"},
    "atlantic": {"ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "DE", "MD",
                 "DC", "WV", "VA", "NC", "SC", "GA", "FL"},
}
FLYWAY_OF = {s: f for f, ss in FLYWAY_STATES.items() for s in ss}
FLYWAY_NAME = {"pacific": "Pacific", "central": "Central",
               "mississippi": "Mississippi", "atlantic": "Atlantic"}


@lru_cache(maxsize=1)
def _polys():
    """[(abbr, bbox, [rings])] for the lower 48 + DC. Holes are ignored; no
    US state outline in this file has an inland hole that matters at 50 km."""
    out = []
    for f in json.load(open(SRC))["features"]:
        ab = ABBR.get(f["properties"]["name"])
        if not ab:
            continue                                   # AK, HI, PR: off the map
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [p[0] for p in polys]
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        out.append((ab, (min(ys), max(ys), min(xs), max(xs)), rings))
    return out


def _inside(ring, lat, lon):
    hit, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


@lru_cache(maxsize=None)
def state_at(lat, lon):
    """Two-letter state the point falls in, or None (ocean, Canada, Mexico)."""
    for ab, (a, b, c, d), rings in _polys():
        if a <= lat <= b and c <= lon <= d and any(_inside(r, lat, lon) for r in rings):
            return ab
    return None


def flyway_at(lat, lon):
    s = state_at(lat, lon)
    return FLYWAY_OF.get(s) if s else None


def nearest_flyway(lat, lon, reach_deg=0.75):
    """Flyway of the point, or of the nearest land within `reach_deg` - so a
    coastal circle centred just offshore still belongs somewhere."""
    f = flyway_at(lat, lon)
    if f:
        return f
    for r in (reach_deg / 2, reach_deg):
        for dla, dlo in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (r, -r), (-r, r), (-r, -r)):
            f = flyway_at(lat + dla, lon + dlo)
            if f:
                return f
    return None
