"""Arc geometry for the upstream watch cone.  See DECISIONS.md D4."""
import math

from .grid import LON_STEP, snap_lat, snap_lon

R_EARTH_MI = 3958.7613

# Named hunt locations. Dove Blasters runs Collin + Grayson County properties
# along the US-75 corridor (Anna, Melissa, Van Alstyne, Howe). Exact field
# coordinates are members-only, so we anchor on the corridor centroid - every
# one of their properties sits within ~25 mi of it, which is far inside the
# resolution this forecast actually has.
LOCATIONS = {
    "doveblasters": (33.391, -96.579, "Dove Blasters — Collin & Grayson Co."),
    "anna":         (33.350, -96.549, "Anna, TX"),
    "melissa":      (33.286, -96.573, "Melissa, TX"),
    "vanalstyne":   (33.421, -96.581, "Van Alstyne, TX"),
    "howe":         (33.507, -96.613, "Howe, TX"),
    "dallas":       (32.780, -96.800, "Dallas, TX"),
}

HOME_KEY = "doveblasters"
HOME = LOCATIONS[HOME_KEY][:2]
HOME_NAME = LOCATIONS[HOME_KEY][2]
SAMPLES_PER_ARC = 9   # denser sampling across the corridor; same request count

# Central Management Unit outer bounds. Doves east of roughly the Mississippi
# belong to the Eastern Management Unit and go down that flyway; the high
# plains west of the Rockies winter further south and west. The corridor is
# always centred on the HUNTER and only clamped by these - the old absolute
# -102/-92 window was one hunter's longitude baked in as if it were geography.
CMU_W, CMU_E = -104.0, -90.0
FLYWAY_W, FLYWAY_E = CMU_W, CMU_E      # legacy names, still imported by wave.py

# A band narrower than this cannot hold independent weather. ECMWF ifs025
# cells are 0.25 deg (~13 mi of longitude), so nine points in a 36-mile window
# all resolve to the same 3-4 cells -- the quorum then reports "9/9 agree"
# when it is one station counted nine times. Silent, and backwards: the
# locations with the LEAST real data would claim the MOST agreement.
MIN_WINDOW_MI = 115.0
CORRIDOR_HALF_MI = 210.0        # half-width of the source corridor

# (index, miles NORTH, label)
# Each band is a constant-latitude segment across the corridor, not an arc.
# The funnel widens with distance until it hits the flyway edges, then stops:
# half-width = min(CORRIDOR_HALF_MI, 0.7 * north_mi). Close in, country 200 mi
# to your east is beside you, not upstream, so band 1 stays narrow.
# Distances are whole multiples of the 0.75 deg lattice row spacing
# (2.25 / 4.50 / 6.75 / 9.00 deg), so band_lat = snapped_user_lat + offset is
# ALWAYS another lattice row exactly. That matters because front_speed_mph
# least-squares-fits passage time against latitude: any snapping jitter on
# that axis would corrupt the measured speed. 3.5% further than the old round
# 150/300/450/600, which is far inside model error.
BANDS = [
    (1, 155.25, "Oklahoma"),         # 2.25 deg
    (2, 310.50, "Southern Kansas"),  # 4.50 deg
    (3, 465.75, "Northern Kansas"),  # 6.75 deg
    (4, 621.00, "Nebraska & Iowa"),  # 9.00 deg
]
ARCS = BANDS



def arc_points(home=HOME, arcs=ARCS, n=SAMPLES_PER_ARC):
    """Constant-latitude bands across the flyway corridor.

    All points in a band share a latitude, which is what makes the front
    tracker honest: 'when did the boundary cross this latitude' is a single
    well-posed question, and the spread across the corridor is the quorum.
    The old cone varied latitude WITHIN a band, muddying both.
    """
    out = {}
    for idx, north_mi, label in arcs:
        lat = home[0] + north_mi / 69.0
        half_mi = min(CORRIDOR_HALF_MI, 0.7 * north_mi)
        half_deg = half_mi / (69.0 * math.cos(math.radians(lat)))
        # Clamp the window's CENTRE into the flyway, never its edges. Clipping
        # edges collapses (and past ~-89.8 inverts) the window for an eastern
        # hunter. Sliding the whole corridor west keeps it full width, and is
        # also where those birds actually come from.
        centre = min(max(home[1], CMU_W + half_deg), CMU_E - half_deg)
        lo, hi = centre - half_deg, centre + half_deg
        # SELECT the lattice columns inside the window rather than generating
        # n evenly-spaced points and snapping them. Snapping collapses several
        # points onto the same node, and the quorum then counts one station
        # repeatedly - the same false-agreement failure as a collapsed window.
        # Point count therefore varies with window width, which is honest:
        # a narrower band genuinely has fewer independent stations.
        c0 = math.ceil(lo / LON_STEP) * LON_STEP
        cols = []
        c = c0
        while c <= hi + 1e-9:
            cols.append(round(c, 4))
            c += LON_STEP
        pts = [(round(lat, 4), c) for c in cols]
        # true distance to the corridor edge, for the bird's flight time
        edge_mi = max(abs(p[1] - home[1]) for p in pts) * 69.0 * math.cos(math.radians(lat))
        mean_mi = (north_mi + math.hypot(north_mi, edge_mi)) / 2.0
        width_mi = (hi - lo) * 69.0 * math.cos(math.radians(lat))
        out[idx] = {"dist_mi": round(mean_mi), "north_mi": north_mi, "label": label,
                    "half_width_mi": round(half_mi), "points": pts,
                    "mean_lat": round(lat, 3), "width_mi": round(width_mi),
                    "usable": width_mi >= MIN_WINDOW_MI}
    return out
