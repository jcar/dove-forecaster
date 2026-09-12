"""Front tracking and arrival ETA.  Turns arc scores into a DATE.

Two separate questions, deliberately not conflated:
  - Does a front exist, and where is it?   -> pure meteorology (raw score)
  - How many birds does it deliver?        -> raw * gate * reservoir (index)
A front is equally real in January; it just has no birds behind it.
"""
import math
from datetime import datetime, timedelta, time
from statistics import mean, median

from .push import southward_push

BIRD_SPEED_MI_PER_DAY = 150.0   # strawman; calibrate against EBD
ARRIVAL_HOUR = 8                # diurnal migrants land in the morning


def frontal_passages(h, min_score=10.0, min_sep_hours=36):
    """Timestamp every frontal passage in an hourly series.

    Daily resolution is too coarse for this: arcs are 150 mi apart and a
    front moving 25 mph crosses that in ~6 hours. Tracking has to work on
    the hourly series or the velocity estimate is pure noise.

    Signature = wind veering southward + pressure trough + temp falling.
    """
    times, t, sp = h["time"], h["temperature_2m"], h["surface_pressure"]
    ws, wd = h["wind_speed_10m"], h["wind_direction_10m"]
    n = len(times)
    push = [None if ws[i] is None or wd[i] is None else southward_push(ws[i], wd[i])
            for i in range(n)]

    scored = []
    for i in range(6, n - 6):
        w = [push[j] for j in range(i - 6, i + 7)] + \
            [t[j] for j in range(i - 6, i + 7)] + [sp[j] for j in range(i - 6, i + 7)]
        if any(v is None for v in w):
            continue
        d_push = mean(push[i + 1:i + 7]) - mean(push[i - 6:i])
        d_pres = mean(sp[i + 1:i + 7]) - mean(sp[i - 6:i])
        d_temp = mean(t[i - 6:i]) - mean(t[i + 1:i + 7])
        scored.append((1.0 * d_push + 2.5 * d_pres + 0.8 * d_temp, i))

    out = []
    for score, i in sorted(scored, reverse=True):
        if score < min_score:
            break
        if all(abs(i - j) >= min_sep_hours for _, j in out):
            out.append((score, i))
    return [(datetime.fromisoformat(times[i]), round(s, 1)) for s, i in sorted(out, key=lambda x: x[1])]


def arc_passage(per_point_hourly, min_points=3):
    """Median passage time across an arc's sample points.

    Requiring a quorum kills single-station artifacts: one gusty point is
    noise, three points in a row is a boundary.
    """
    firsts = []
    for h in per_point_hourly:
        p = frontal_passages(h)
        if p:
            firsts.append(p)
    if len(firsts) < min_points:
        return None
    # group by the strongest passage at each point
    best = [max(p, key=lambda x: x[1]) for p in firsts]
    ts = sorted(dt.timestamp() for dt, _ in best)
    return {"when": datetime.fromtimestamp(median(ts)),
            "strength": round(mean(s for _, s in best), 1),
            "points_firing": len(firsts)}


def cluster_fronts(events, min_speed_mph=7.0):
    """Group arc passages into DISTINCT boundaries before measuring anything.

    Without this the speed fit is garbage. Arc 4/3/2 firing over 22 hours is
    one front; Arc 1 firing four days later is a different weather system
    entirely. Regressing a line through both produces a front that moves at
    3 mph, which is not a thing.
    """
    fronts = []
    for e in sorted(events, key=lambda x: -x["dist_mi"]):
        for f in fronts:
            prev = f[-1]
            gap_mi = prev["dist_mi"] - e["dist_mi"]
            gap_h = (e["when"] - prev["when"]).total_seconds() / 3600.0
            if 0 <= gap_h <= max(6.0, gap_mi / min_speed_mph):
                f.append(e)
                break
        else:
            fronts.append([e])
    return fronts


def front_speed_mph(events):
    """Least-squares southward speed from (latitude, passage time) pairs.

    The front's own velocity across the arcs is the measurement that turns
    'a front is coming' into 'Thursday'. We are not assuming a speed.
    """
    pts = [(e["mean_lat"], e["when"].timestamp() / 3600.0) for e in events]
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mx, my = mean(xs), mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pts) / den   # hours per degree lat
    if slope >= -0.1:        # not propagating southward
        return None
    spd = 69.0 / abs(slope)
    return round(spd, 1) if 5.0 <= spd <= 70.0 else None   # sanity band


def arrival_forecast(events, days_out=10, today=None, speed=BIRD_SPEED_MI_PER_DAY):
    """Superpose one bird pulse per arc.

    Birds do not ride the front in. They DEPART when the front clears the
    latitude they're staged at, then fly south at their own pace. So each
    arc contributes a pulse arriving at its own lead time, and the big days
    are when pulses from several arcs land together.
    """
    today = today or datetime.now().date()
    out = []
    for k in range(days_out):
        d = today + timedelta(days=k)
        target = datetime.combine(d, time(ARRIVAL_HOUR))
        total, parts = 0.0, []
        for e in events:
            center = e["when"] + timedelta(days=e["dist_mi"] / speed)
            sigma = 0.35 + e["dist_mi"] / 1200.0      # distant arcs arrive smeared
            dt_d = (target - center).total_seconds() / 86400.0
            w = math.exp(-0.5 * (dt_d / sigma) ** 2)
            c = e["index"] * w
            total += c
            if c > 1.0:
                parts.append((e["arc"], round(c, 1)))
        out.append({"date": d.isoformat(), "arrival": round(total, 1),
                    "from_arcs": sorted(parts, key=lambda x: -x[1])})
    return out
