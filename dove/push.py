"""Push Index v0.  See DECISIONS.md D5.

    raw = wind(0-35) + tempdrop(0-25) + pressure(0-20)
        + clearing(0-10) + sharpness(0-10)
    index = raw * photoperiod_gate * reservoir
"""
import math
from datetime import date

WIND_MAX, TEMP_MAX, PRES_MAX, CLEAR_MAX, SHARP_MAX = 35, 25, 20, 10, 10


def ramp(x, lo, hi, max_pts):
    if x <= lo:
        return 0.0
    if x >= hi:
        return float(max_pts)
    return max_pts * (x - lo) / (hi - lo)


def southward_push(speed_mph, dir_from_deg):
    """Meteorological direction is where wind comes FROM.
    Wind from 000 pushes due south at full speed; from 340 still ~94%.
    Using the vector, not a compass label, keeps the near-misses."""
    return speed_mph * math.cos(math.radians(dir_from_deg))


def day_length_hours(lat, doy):
    decl = 0.4093 * math.sin(2 * math.pi * (doy - 81) / 365.0)
    cos_h = max(-1.0, min(1.0, -math.tan(math.radians(lat)) * math.tan(decl)))
    return 24.0 * math.acos(cos_h) / math.pi


def photoperiod_gate(lat, doy, open_doy_at_33=258, days_per_deg=1.6, ramp_days=18):
    """Seasonal availability gate, 0-1.  Northern arcs must open EARLIER.

    IMPLEMENTATION NOTE - the obvious version does not work.  An absolute
    day-length threshold (e.g. "gate opens when daylight < 12.5h") is not
    latitude-ordered in early fall: near the equinox day length is almost
    latitude-independent, and the small residual difference runs BACKWARDS.
    33N falls through 12.5h a few days BEFORE 41N does, so an absolute
    threshold opens the SOUTHERN arcs first - the opposite of reality.

    So: day-of-year shifted by latitude instead.  Strawman constants;
    calibrate against EBD.  ~Sep 15 at 33N, ~Sep 2 at 41N.
    """
    open_doy = open_doy_at_33 - days_per_deg * (lat - 33.0)
    return ramp(doy, open_doy, open_doy + ramp_days, 1.0)


class Reservoir:
    """Each arc holds a finite population that depletes and does not refill.
    First hard front of the fall >> the fourth identical one."""

    def __init__(self, k=0.25):
        self.level, self.k = 1.0, k

    def debit(self, raw):
        self.level *= (1.0 - self.k * (raw / 100.0))
        return self.level


def daily_features(h, daylight=(6, 14)):
    """Collapse an hourly series into per-day features.
    Wind is sampled in DAYLIGHT ONLY - doves are diurnal migrants."""
    days = {}
    for i, ts in enumerate(h["time"]):
        d, hr = ts[:10], int(ts[11:13])
        t, ws = h["temperature_2m"][i], h["wind_speed_10m"][i]
        wd, sp, cc = h["wind_direction_10m"][i], h["surface_pressure"][i], h["cloud_cover"][i]
        if None in (t, ws, wd, sp, cc):
            continue
        f = days.setdefault(d, {"temps": [], "push": [], "pres": [], "cloud_am": [], "day_t": []})
        f["temps"].append(t)
        f["pres"].append(sp)
        if 10 <= hr < 18:
            # Daytime only. A temp DROP while the sun is up is a frontal
            # signature; scanning all 24h just rediscovers sunset.
            f["day_t"].append(t)
        if daylight[0] <= hr < daylight[1]:
            f["push"].append(southward_push(ws, wd))
        if 6 <= hr < 12:
            f["cloud_am"].append(cc)
    out = {}
    for d, f in days.items():
        if len(f["temps"]) < 20:      # drop partial days
            continue
        drops = [f["day_t"][i - 1] - f["day_t"][i] for i in range(1, len(f["day_t"]))]
        out[d] = {
            "tmax": max(f["temps"]),
            "wind_push": max(f["push"]) if f["push"] else 0.0,
            "p_mean": sum(f["pres"]) / len(f["pres"]),
            "cloud_am": sum(f["cloud_am"]) / len(f["cloud_am"]) if f["cloud_am"] else 50.0,
            "max_hourly_drop": max(drops) if drops else 0.0,
        }
    return out


def score_day(cur, prev, lat, d_iso, reservoir_level):
    """Score one day at one location.  Returns component breakdown - the
    'why' string is the trust engine, so nothing is allowed to be opaque."""
    if prev is None:
        return None
    doy = date.fromisoformat(d_iso).timetuple().tm_yday
    c = {
        "wind":     ramp(cur["wind_push"], 5, 22, WIND_MAX),
        "tempdrop": ramp(prev["tmax"] - cur["tmax"], 4, 22, TEMP_MAX),
        "pressure": ramp(cur["p_mean"] - prev["p_mean"], 1, 7, PRES_MAX),
        # Clearing is a CHANGE, not a state. A clear stagnant August day is
        # not post-frontal; cloud cover falling 40 points overnight is.
        "clearing": ramp(prev["cloud_am"] - cur["cloud_am"], 10, 50, CLEAR_MAX),
        "sharp":    ramp(cur["max_hourly_drop"], 1.0, 3.5, SHARP_MAX),
    }
    raw = sum(c.values())
    gate = photoperiod_gate(lat, doy)
    return {
        "raw": raw, "gate": gate, "reservoir": reservoir_level,
        "index": raw * gate * reservoir_level, "components": c,
        "obs": {"push_mph": cur["wind_push"],
                "temp_drop": prev["tmax"] - cur["tmax"],
                "pres_rise": cur["p_mean"] - prev["p_mean"],
                "cloud_am": cur["cloud_am"]},
    }
