"""Arc geometry for the upstream watch cone.  See DECISIONS.md D4."""
import math

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

# Central Management Unit working bounds. Doves east of roughly the
# Mississippi belong to the Eastern Management Unit and go down that flyway,
# not to North Texas; the high plains west of ~102W winter further south and
# west. Sampling outside these feeds us birds that were never coming here.
FLYWAY_W, FLYWAY_E = -102.0, -92.0
CORRIDOR_HALF_MI = 210.0        # half-width of the source corridor

# (index, miles NORTH, label)
# Each band is a constant-latitude segment across the corridor, not an arc.
# The funnel widens with distance until it hits the flyway edges, then stops:
# half-width = min(CORRIDOR_HALF_MI, 0.7 * north_mi). Close in, country 200 mi
# to your east is beside you, not upstream, so band 1 stays narrow.
BANDS = [
    (1, 150, "Oklahoma"),            # OKC · Shawnee · Fort Smith
    (2, 300, "Southern Kansas"),     # Dodge City · Wichita · Springfield MO
    (3, 450, "Northern Kansas"),     # Norton · Marysville · N Missouri
    (4, 600, "Nebraska & Iowa"),     # Valentine · Norfolk · Waterloo
]
ARCS = BANDS


def destination(lat, lon, bearing_deg, dist_mi):
    """Great-circle destination from a point given bearing and distance."""
    lat1, lon1 = math.radians(lat), math.radians(lon)
    brg, d = math.radians(bearing_deg), dist_mi / R_EARTH_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) +
                     math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return round(math.degrees(lat2), 4), round((math.degrees(lon2) + 540) % 360 - 180, 4)


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
        lo = max(home[1] - half_deg, FLYWAY_W)
        hi = min(home[1] + half_deg, FLYWAY_E)
        pts = [(round(lat, 4), round(lo + (hi - lo) * i / (n - 1), 4)) for i in range(n)]
        # true distance to the corridor edge, for the bird's flight time
        edge_mi = max(abs(p[1] - home[1]) for p in pts) * 69.0 * math.cos(math.radians(lat))
        mean_mi = (north_mi + math.hypot(north_mi, edge_mi)) / 2.0
        out[idx] = {"dist_mi": round(mean_mi), "north_mi": north_mi, "label": label,
                    "half_width_mi": round(half_mi), "points": pts,
                    "mean_lat": round(lat, 3)}
    return out
