"""The lattice nodes the animation needs — sites plus every band point."""
from .flyway import catalogue
from .geo import arc_points
from .grid import snap


def lattice_nodes():
    sites = catalogue()
    pts = {snap(s["lat"], s["lon"]) for s in sites}
    for s in sites:
        for b in arc_points((s["lat"], s["lon"])).values():
            for p in b["points"]:
                pts.add(snap(*p))
    return sorted(pts)
