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
CONE_CENTER_BEARING = 0.0       # due north
SAMPLES_PER_ARC = 5

# (index, distance_mi, cone half-angle deg, label)
# Half-angle widens with distance: TX is a wintering funnel, so the
# contributing breeding range fans out the further north you look.
ARCS = [
    (1, 150, 30, "S Oklahoma / Red River"),
    (2, 300, 35, "Central + NE Oklahoma"),
    (3, 450, 40, "Kansas"),
    (4, 600, 45, "Nebraska / NW Missouri"),
]


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
    out = {}
    for idx, dist, half, label in arcs:
        pts = [destination(home[0], home[1],
                           CONE_CENTER_BEARING + ((i / (n - 1)) * 2 - 1) * half,
                           dist)
               for i in range(n)]
        out[idx] = {"dist_mi": dist, "label": label, "half_angle": half,
                    "points": pts,
                    "mean_lat": round(sum(p[0] for p in pts) / len(pts), 3)}
    return out
