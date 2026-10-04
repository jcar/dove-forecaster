"""Wind at a height ABOVE THE GROUND, and when the sun sets (D26).

925 hPa sits about 750 m up at sea level, but over Denver (surface ~840 hPa)
it is underground: the model's value there is an extrapolation through rock.
Birds fly at a height above the ground, so that is what we sample:

    doves  - low, by day: the 100 m wind
    ducks  - ~490 +- 163 m AGL at night (O'Neal et al. 2010, 2018): the wind
             interpolated to (surface pressure - 50 hPa), about 450 m up.

The vertical profile is the 100 m wind (anchored ~12 hPa above the surface)
plus whichever of 1000/925/850/700 hPa are actually above the ground at that
hour, interpolated linearly in log-pressure as u/v components.
"""
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LEVELS = (1000, 925, 850, 700)
DUCK_AGL_HPA = 50.0          # ~450 m above ground
ANCHOR_HPA = 12.0            # 100 m above ground is ~12 hPa


def _uv(speed, frm):
    r = math.radians(frm)
    return -speed * math.sin(r), -speed * math.cos(r)


def _sd(u, v):
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def wind_at_agl(h, i, dp=DUCK_AGL_HPA):
    """(speed, direction-from) at `dp` hPa above the surface for hour i, or None."""
    sp = h.get("surface_pressure", [None])[i] if h.get("surface_pressure") else None
    if sp is None:
        return None
    prof = []
    if h.get("wind_speed_100m") and h["wind_speed_100m"][i] is not None \
            and h["wind_direction_100m"][i] is not None:
        prof.append((sp - ANCHOR_HPA, *_uv(h["wind_speed_100m"][i], h["wind_direction_100m"][i])))
    for lv in LEVELS:
        s, d = h.get(f"wind_speed_{lv}hPa"), h.get(f"wind_direction_{lv}hPa")
        if s and d and s[i] is not None and d[i] is not None and lv < sp - ANCHOR_HPA:
            prof.append((float(lv), *_uv(s[i], d[i])))      # only levels above the ground
    if not prof:
        return None
    prof.sort(key=lambda x: -x[0])                          # surface first, going up
    target = sp - dp
    if target >= prof[0][0]:
        return _sd(prof[0][1], prof[0][2])
    for a, b in zip(prof, prof[1:]):
        if a[0] >= target >= b[0]:
            f = (math.log(a[0]) - math.log(target)) / (math.log(a[0]) - math.log(b[0]))
            return _sd(a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
    return _sd(prof[-1][1], prof[-1][2])                    # very high ground: top level


def add_agl(h, dp=DUCK_AGL_HPA):
    """Adds wind_speed_agl / wind_direction_agl in place, if the profile
    fields are present. Idempotent."""
    if "wind_speed_agl" in h or not any(f"wind_speed_{lv}hPa" in h for lv in LEVELS):
        return h
    sp_, dr_ = [], []
    for i in range(len(h["time"])):
        w = wind_at_agl(h, i, dp)
        sp_.append(None if w is None else round(w[0], 1))
        dr_.append(None if w is None else round(w[1]))
    h["wind_speed_agl"], h["wind_direction_agl"] = sp_, dr_
    return h


def sunset_local(lat, lon, day_iso, tz):
    """Local clock time of sunset as fractional hours (NOAA approximation,
    good to a few minutes - far finer than the hourly data it gates)."""
    d = date.fromisoformat(day_iso)
    n = d.timetuple().tm_yday
    g = 2 * math.pi / 365.0 * (n - 1)
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g))
    cos_h = (math.cos(math.radians(90.833)) / (math.cos(math.radians(lat)) * math.cos(decl))
             - math.tan(math.radians(lat)) * math.tan(decl))
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_h))))
    utc_min = 720 - 4 * (lon - ha) - eot
    t = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=utc_min)
    loc = t.astimezone(ZoneInfo(tz))
    return loc.hour + loc.minute / 60.0 + (24 if loc.date() > d else 0)
