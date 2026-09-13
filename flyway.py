#!/usr/bin/env python3
"""Export the moving picture: a real 2D wind field, real forecast locations,
and real state outlines — projected at build time so the page needs no
mapping library at all.

Nothing here is modelled. The wind is measured and already cached; the
arrivals are 152 independent forecasts, each for the place it is drawn at.
Birds are never drawn between locations, because the flight model has no
east-west coordinate to put them at.
"""
import json, math, os

# Albers Equal Area Conic, the standard projection for the contiguous US.
# Static — no pan, no zoom — so it is computed once here rather than shipping
# a projection library to every phone that opens the page.
PHI0, LAM0 = math.radians(23.0), math.radians(-96.0)
PHI1, PHI2 = math.radians(29.5), math.radians(45.5)
_N = (math.sin(PHI1) + math.sin(PHI2)) / 2.0
_C = math.cos(PHI1) ** 2 + 2 * _N * math.sin(PHI1)
_RHO0 = math.sqrt(_C - 2 * _N * math.sin(PHI0)) / _N


def albers(lat, lon):
    theta = _N * (math.radians(lon) - LAM0)
    rho = math.sqrt(max(0.0, _C - 2 * _N * math.sin(math.radians(lat)))) / _N
    return rho * math.sin(theta), _RHO0 - rho * math.cos(theta)


class Fit:
    """Map projected coordinates into an SVG viewBox."""

    def __init__(self, box, w, h, pad=12, n=40):
        """box is (lat0, lat1, lon0, lon1). Albers is conic, so the extreme
        projected coordinates are NOT at the box corners - a corner-only fit
        pushes the southern tip off the bottom of the viewBox. Sample the
        whole perimeter instead."""
        (la0, la1, lo0, lo1) = box
        pts = []
        for i in range(n + 1):
            t = i / n
            pts += [(la0 + (la1 - la0) * t, lo0), (la0 + (la1 - la0) * t, lo1),
                    (la0, lo0 + (lo1 - lo0) * t), (la1, lo0 + (lo1 - lo0) * t)]
        xs, ys = [], []
        for lat, lon in pts:
            x, y = albers(lat, lon)
            xs.append(x); ys.append(y)
        self.x0, self.x1 = min(xs), max(xs)
        self.y0, self.y1 = min(ys), max(ys)
        sx = (w - 2 * pad) / (self.x1 - self.x0)
        sy = (h - 2 * pad) / (self.y1 - self.y0)
        self.s = min(sx, sy)
        self.dx = pad + ((w - 2 * pad) - self.s * (self.x1 - self.x0)) / 2
        self.dy = pad + ((h - 2 * pad) - self.s * (self.y1 - self.y0)) / 2

    def __call__(self, lat, lon):
        x, y = albers(lat, lon)
        # SVG y grows downward; projected y grows north, so flip
        return (round(self.dx + (x - self.x0) * self.s, 1),
                round(self.dy + (self.y1 - y) * self.s, 1))


def ring_path(fit, ring, min_step=0.8):
    """One projected polygon as an SVG path, dropping points that would land
    within min_step pixels of the last kept one (cheap simplification)."""
    out, last = [], None
    for lon, lat in ring:
        p = fit(lat, lon)
        if last is None or abs(p[0] - last[0]) + abs(p[1] - last[1]) >= min_step:
            out.append(p); last = p
    if len(out) < 3:
        return None
    return "M" + "L".join(f"{x},{y}" for x, y in out) + "Z"


def geometry_paths(geojson, states, fit):
    """Projected outlines for the states we draw."""
    paths = {}
    for feat in geojson["features"]:
        name = (feat.get("properties", {}).get("name")
                or feat.get("properties", {}).get("NAME"))
        if name not in states:
            continue
        g, rings = feat["geometry"], []
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for ring in poly:
                d = ring_path(fit, ring)
                if d:
                    rings.append(d)
        if rings:
            paths[name] = " ".join(rings)
    return paths


# ---------------------------------------------------------------------------
MAP_W, MAP_H = 480, 640
MAP_BOX = (25.5, 49.5, -107.0, -89.0)          # the country the lattice covers
DRAW_STATES = ["Texas", "Oklahoma", "Kansas", "Nebraska", "New Mexico", "Colorado",
               "Missouri", "Arkansas", "Louisiana", "South Dakota", "North Dakota",
               "Iowa", "Minnesota", "Wyoming", "Montana"]
OUT = "docs/data"


def build_geo(src, out=f"{OUT}/geo.json"):
    """Project the state outlines once. Geometry never changes, so this is not
    part of the daily build and the page never loads a mapping library."""
    fit = Fit(MAP_BOX, MAP_W, MAP_H)
    paths = geometry_paths(json.load(open(src)), set(DRAW_STATES), fit)
    json.dump({"w": MAP_W, "h": MAP_H, "box": MAP_BOX, "paths": paths},
              open(out, "w"), separators=(",", ":"))
    return out, os.path.getsize(out), len(paths)


def export(cache, sites, dates, out=f"{OUT}/flow.json"):
    """The moving field.

    Wind comes from the 2D lattice cache DIRECTLY, never from
    engine.push_field: that collapses to a single latitude row on historical
    dates, and would silently paint one hunter's local wind across the entire
    plains.
    """
    fit = Fit(MAP_BOX, MAP_W, MAP_H)
    nodes = sorted(cache._feat)
    lats = sorted({p[0] for p in nodes})
    lons = sorted({p[1] for p in nodes})
    li = {v: i for i, v in enumerate(lats)}
    oi = {v: i for i, v in enumerate(lons)}

    # The lattice's fill pattern is the SAME every day (79% of a 30x17
    # rectangle), so ship the mask once and one flat array of ints per date
    # instead of a grid of mostly-repeated nulls. Cuts the payload ~3x.
    # Cells outside the mask are drawn as gaps - never as calm, which would
    # be inventing weather.
    mask = [[li[la], oi[lo]] for (la, lo) in nodes]
    wind = []
    for d in dates:
        frame = []
        for (la, lo) in nodes:
            v = cache._feat[(la, lo)].get(d)
            frame.append(round(v["wind_push"]) if v is not None else None)
        wind.append(frame)

    site_out = []
    for s in sites:
        by = {r["date"]: r["arrival"] for r in s["arrival"]}
        site_out.append({"id": s["id"], "xy": fit(s["lat"], s["lon"]),
                         "a": [round(by.get(d, 0.0), 1) for d in dates]})

    # Frontal passages on the real 2D lattice, bucketed by day. Stored as
    # INDICES into the mask we already ship, not as coordinate pairs - the
    # positions are the same nodes, so repeating them costs ~3x for nothing.
    node_idx = {pt: i for i, pt in enumerate(nodes)}
    dset = set(dates)
    fronts = {}
    for pt, passes in cache._pass.items():
        for when, strength in passes:
            d = when.date().isoformat()
            if d in dset:
                fronts.setdefault(d, []).append(node_idx[pt])

    # one screen position per MASKED node, in the same order as each frame
    grid = {"lats": lats, "lons": lons,
            "xy": [fit(la, lo) for (la, lo) in nodes],
            "cell": [round(abs(fit(lats[0], lons[0])[0] - fit(lats[0], lons[1])[0]), 1),
                     round(abs(fit(lats[0], lons[0])[1] - fit(lats[1], lons[0])[1]), 1)]}
    payload = {"w": MAP_W, "h": MAP_H, "dates": dates, "grid": grid,
               "mask": mask, "wind": wind, "sites": site_out,
               "fronts": [{"date": d, "n": sorted(set(v))} for d, v in sorted(fronts.items())]}
    json.dump(payload, open(out, "w"), separators=(",", ":"))
    return out, os.path.getsize(out)


class DiskField:
    """Hydrate the whole lattice from the on-disk cache, for exporting or
    testing without a live build. Shape-compatible with grid.PointCache."""

    def __init__(self, cache_dir="data/wxcache"):
        from datetime import datetime
        import glob
        self._feat, self._pass = {}, {}
        for p in glob.glob(os.path.join(cache_dir, "*.json")):
            la, lo = os.path.basename(p)[:-5].split("_")
            pt = (float(la), float(lo))
            d = json.load(open(p))
            self._feat[pt] = d.get("features", {})
            self._pass[pt] = [(datetime.fromisoformat(t), s) for t, s in d.get("passages", [])]


def dates_covered(cache):
    ds = set()
    for feat in cache._feat.values():
        ds |= set(feat)
    return sorted(ds)


if __name__ == "__main__":
    import sys
    if "--geo" in sys.argv:
        src = sys.argv[sys.argv.index("--geo") + 1]
        p, sz, n = build_geo(src)
        print(f"wrote {p}  {sz/1000:.0f} KB  {n} state outlines")
    if "--dry" in sys.argv:
        import glob
        c = DiskField()
        ds = dates_covered(c)[-30:]
        sites = []
        for fp in sorted(glob.glob(f"{OUT}/loc/*.json")):
            s = json.load(open(fp)); sites.append(s)
        p, sz = export(c, sites, ds)
        print(f"wrote {p}  {sz/1000:.0f} KB  |  {len(ds)} dates, "
              f"{len(c._feat)} nodes, {len(sites)} sites")
