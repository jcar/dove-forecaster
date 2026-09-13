"""Conditions at the fields themselves — what it's doing where you stand.

The arrival forecast answers WHICH MORNING. This answers what you'll walk
into once you get there: sunrise, wind, temperature, rain.

Wind direction is the one that changes where you stand. Doves turn into the
wind to land, so they come at you from downwind — set up with the wind at
your back and the birds work toward you instead of flaring off your back.
"""
import math
from datetime import datetime

from .weather import OpenMeteo

# surface_pressure is here so the SAME frontal detector we run on the
# northern bands can be run on the hunter's own location — measuring the
# front's arrival instead of extrapolating it 600 miles in a straight line.
LOCAL_HOURLY = ["temperature_2m", "wind_speed_10m", "wind_direction_10m",
                "wind_gusts_10m", "precipitation_probability", "cloud_cover",
                "surface_pressure"]
LOCAL_DAILY = ["sunrise", "sunset"]

# Deliberately NO shooting-hours or season logic here. This is a bird
# forecaster, not a regulations service: eight states, rules that change
# every year, and being wrong is a citation for the user. Sunrise and sunset
# are astronomy and always true; legal hours belong to the state agency.

POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    return POINTS[int((deg % 360) / 22.5 + 0.5) % 16]


def _circular_mean(degs):
    """Wind direction is an angle, so a plain average is wrong: 350 and 10
    average to 180 (due south) instead of 0 (due north)."""
    if not degs:
        return None
    x = sum(math.cos(math.radians(d)) for d in degs)
    y = sum(math.sin(math.radians(d)) for d in degs)
    if x == 0 and y == 0:
        return None
    return math.degrees(math.atan2(y, x)) % 360


def _window(h, idx_from, idx_to):
    """Summarise an hourly slice into what a hunter would actually ask."""
    sl = lambda k: [h[k][i] for i in range(idx_from, idx_to)
                    if i < len(h[k]) and h[k][i] is not None]
    temps, spd = sl("temperature_2m"), sl("wind_speed_10m")
    gust, dirs = sl("wind_gusts_10m"), sl("wind_direction_10m")
    rain, cloud = sl("precipitation_probability"), sl("cloud_cover")
    if not temps or not spd:
        return None
    d = _circular_mean(dirs)
    return {
        "temp_f": round(sum(temps) / len(temps)),
        "wind_mph": round(sum(spd) / len(spd)),
        "gust_mph": round(max(gust)) if gust else None,
        "wind_dir": round(d) if d is not None else None,
        "wind_from": compass(d) if d is not None else None,
        "rain_pct": round(max(rain)) if rain else None,
        "cloud_pct": round(sum(cloud) / len(cloud)) if cloud else None,
    }


def conditions(home, forecast_days=10, want_hourly=False):
    """Per-day morning and evening conditions at the hunter's own location."""
    res = OpenMeteo().hourly([home], forecast_days=forecast_days,
                             hourly=LOCAL_HOURLY, daily=LOCAL_DAILY)[0]
    h, dly = res["hourly"], res["daily"]
    index = {t: i for i, t in enumerate(h["time"])}

    out = []
    for k, day in enumerate(dly["time"]):
        sr, ss = dly["sunrise"][k], dly["sunset"][k]
        if not sr or not ss:
            continue
        sr_dt, ss_dt = datetime.fromisoformat(sr), datetime.fromisoformat(ss)

        def hour_index(dt_):
            return index.get(dt_.replace(minute=0, second=0).isoformat(timespec="minutes"))

        i_sr, i_ss = hour_index(sr_dt), hour_index(ss_dt)
        morning = _window(h, i_sr, i_sr + 3) if i_sr is not None else None
        evening = _window(h, max(0, i_ss - 3), i_ss) if i_ss is not None else None

        out.append({
            "date": day,
            "sunrise": sr_dt.strftime("%H:%M"),
            "sunset": ss_dt.strftime("%H:%M"),
            "morning": morning,
            "evening": evening,
        })
    return (out, h) if want_hourly else out
