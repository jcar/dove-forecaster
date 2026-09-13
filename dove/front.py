"""Front tracking and arrival ETA.  Turns arc scores into a DATE.

Two separate questions, deliberately not conflated:
  - Does a front exist, and where is it?   -> pure meteorology (raw score)
  - How many birds does it deliver?        -> raw * gate * reservoir (index)
A front is equally real in January; it just has no birds behind it.
"""
import math
from datetime import datetime, timedelta, time, date
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


def arc_passages_season(per_point_hourly, min_points=3, tol_hours=18):
    """EVERY frontal passage across a long series, grouped across an arc.

    arc_passage() takes the single strongest passage and is fine for a
    10-day forecast window. A 93-day season has 10-20 boundaries, so they
    have to be clustered in time and quorum-checked individually.
    """
    allp = []
    for pi, h in enumerate(per_point_hourly):
        for dt, s in frontal_passages(h):
            allp.append((dt, s, pi))
    allp.sort(key=lambda x: x[0])

    groups, cur = [], []
    for item in allp:
        if cur and (item[0] - cur[-1][0]).total_seconds() / 3600.0 > tol_hours:
            groups.append(cur)
            cur = []
        cur.append(item)
    if cur:
        groups.append(cur)

    out = []
    for g in groups:
        best = {}
        for dt, s, p in g:
            if p not in best or s > best[p][1]:
                best[p] = (dt, s)
        if len(best) < min_points:
            continue
        ts = sorted(dt.timestamp() for dt, _ in best.values())
        out.append({"when": datetime.fromtimestamp(median(ts)),
                    "strength": round(mean(s for _, s in best.values()), 1),
                    "points_firing": len(best)})
    return out


def cluster_fronts(events, min_speed_mph=7.0):
    """Group arc passages into DISTINCT boundaries before measuring anything.

    Without this the speed fit is garbage. Arc 4/3/2 firing over 22 hours is
    one front; Arc 1 firing four days later is a different weather system
    entirely. Regressing a line through both produces a front that moves at
    3 mph, which is not a thing.
    """
    fronts = []
    for e in sorted(events, key=lambda x: x["when"]):
        best, best_gap = None, None
        for f in fronts:
            prev = f[-1]
            gap_mi = prev["dist_mi"] - e["dist_mi"]
            if gap_mi <= 0:                       # must move inward
                continue
            gap_h = (e["when"] - prev["when"]).total_seconds() / 3600.0
            if 0 <= gap_h <= max(6.0, gap_mi / min_speed_mph):
                if best_gap is None or gap_h < best_gap:
                    best, best_gap = f, gap_h
        if best is not None:
            best.append(e)
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


# ---------------------------------------------------------------------------
# Wind-driven arrival. See DECISIONS.md F13.
#
# The old model flew birds a flat 150 mi/day regardless of what the weather
# did en route, so they could outrun a dying front. They can't: a dove rides
# a north wind, and when it quits the bird sits down and waits for the next
# one. We have wind at five latitudes between Nebraska and the fields, so we
# march them south a day at a time at the speed the sky actually gives them.
BASE_MI_PER_DAY = 25.0      # drift with no help — staging, local shuffling
PUSH_GAIN = 13.0            # extra miles per day per mph of southward wind
MAX_MI_PER_DAY = 260.0      # a hard day's flight on a strong tailwind


def daily_flight_mi(push_mph):
    return max(0.0, min(MAX_MI_PER_DAY, BASE_MI_PER_DAY + PUSH_GAIN * push_mph))


def push_at(push_field, day_iso, lat):
    """Southward wind push at a latitude, linearly interpolated between the
    latitudes we actually sample (the four bands plus the fields)."""
    row = push_field.get(day_iso)
    if not row:
        return 0.0
    lats = sorted(row)
    if lat <= lats[0]:
        return row[lats[0]]
    if lat >= lats[-1]:
        return row[lats[-1]]
    for a, b in zip(lats, lats[1:]):
        if a <= lat <= b:
            f = 0.0 if b == a else (lat - a) / (b - a)
            return row[a] * (1 - f) + row[b] * f
    return 0.0


def simulate_arrival(depart_day, north_mi, push_field, home_lat, max_days=16):
    """March one departure south. Returns fractional days to the fields, or
    None if they are still in the air past the horizon."""
    remaining, day = float(north_mi), date.fromisoformat(depart_day)
    for n in range(1, max_days + 1):
        day += timedelta(days=1)
        lat = home_lat + remaining / 69.0
        flown = daily_flight_mi(push_at(push_field, day.isoformat(), lat))
        if flown >= remaining:
            # land partway through the day rather than snapping to midnight
            return n - 1 + (remaining / flown if flown else 1.0)
        remaining -= flown
    return None


def arrival_forecast_wind(events, push_field, home_lat, days_out=10,
                          today=None, spread=0.6):
    """Superpose per-band pulses, each timed by an actual simulated flight."""
    today = today or datetime.now().date()
    legs = []
    for e in events:
        lead = simulate_arrival(e["when"].date().isoformat(), e["north_mi"],
                                push_field, home_lat)
        if lead is None:
            continue          # still airborne past the horizon
        legs.append((e, e["when"] + timedelta(days=lead), lead))

    out = []
    for k in range(days_out):
        d = today + timedelta(days=k)
        target = datetime.combine(d, time(ARRIVAL_HOUR))
        total, parts = 0.0, []
        for e, centre, lead in legs:
            # a longer, more interrupted flight arrives more smeared out
            sigma = spread + 0.12 * lead
            dt_d = (target - centre).total_seconds() / 86400.0
            c = e["index"] * math.exp(-0.5 * (dt_d / sigma) ** 2)
            total += c
            if c > 1.0:
                parts.append((e["arc"], round(c, 1)))
        out.append({"date": d.isoformat(), "arrival": round(total, 1),
                    "from_arcs": sorted(parts, key=lambda x: -x[1])})
    return out
