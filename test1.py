#!/usr/bin/env python3
"""TEST 1 — does the Push Index predict actual doves?

Arrival is reconstructed by CONVOLUTION over each arc's daily index rather
than from discrete detected fronts. Two reasons: it needs nothing but
arc_scores, and it doesn't inherit the front detector's threshold choices —
so a failure here is a failure of the biology, not of event detection.

    arrival(d) = SUM_arc SUM_day  index[arc][day] * K(d - day - lead[arc])

Every comparison is run against the migratory species AND against
Eurasian Collared-Dove, which does not migrate. The control is the test:
if both correlate, we are measuring observers, not birds.
"""
import json, glob, math, sys
from datetime import date, timedelta
from statistics import median

SPEED = 150.0           # bird ground speed, mi/day (strawman)
DIST = {1: 150, 2: 300, 3: 450, 4: 600}


def arrival_series(arc_scores, speed=SPEED):
    days = sorted({d for a in arc_scores.values() for d in a})
    out = {}
    for tgt in days:
        t = date.fromisoformat(tgt)
        tot = 0.0
        for a_s, ser in arc_scores.items():
            a = int(a_s)
            lead, sig = DIST[a] / speed, 0.35 + DIST[a] / 1200.0
            for d, v in ser.items():
                idx = v["index"] if isinstance(v, dict) else v
                if not idx:
                    continue
                off = (t - date.fromisoformat(d)).days - lead
                if abs(off) > 4 * sig:
                    continue
                tot += idx * math.exp(-0.5 * (off / sig) ** 2)
        out[tgt] = round(tot, 3)
    return out


def anomaly(series, win=9):
    """Subtract a centred rolling median. Both series carry a strong seasonal
    trend; correlating the raw levels would mostly measure autumn."""
    ks = sorted(series)
    out = {}
    for i, k in enumerate(ks):
        lo, hi = max(0, i - win // 2), min(len(ks), i + win // 2 + 1)
        base = median([series[ks[j]] for j in range(lo, hi)])
        out[k] = series[k] - base
    return out


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def corr(xs, ys, spearman=True):
    if len(xs) < 6:
        return None
    if spearman:
        xs, ys = _rank(xs), _rank(ys)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def load_ebird(min_lists=8):
    out = {}
    for p in sorted(glob.glob("data/ebird/*.json")):
        d = json.load(open(p))
        if d["n_complete"] < min_lists:
            continue          # thin days are noise, not signal
        out[d["date"]] = {s: d["species"][s]["per_hour"] for s in
                          ("moudov", "whwdov", "eucdov")}
    return out


def run(years=None):
    eb = load_ebird()
    arr = {}
    for p in sorted(glob.glob("data/backtest/*.json")):
        d = json.load(open(p))
        if years and d["year"] not in years:
            continue
        arr.update(arrival_series(d["arc_scores"]))
    for p in sorted(glob.glob("data/forecasts/*.json")):
        arr.update(arrival_series(json.load(open(p))["arc_scores"]))

    shared = sorted(set(arr) & set(eb))
    print(f"overlapping days: {len(shared)}")
    if len(shared) < 10:
        print("NOT ENOUGH OVERLAP — need eBird days in seasons we have weather for.")
        print(f"  weather-season days: {len(arr)}   ebird days: {len(eb)}")
        return

    aa = anomaly({d: arr[d] for d in shared})
    print(f"\n{'species':<26}" + "".join(f"lag{l:+d}".rjust(9) for l in range(-3, 4)))
    for sp, name in (("moudov", "Mourning Dove"), ("whwdov", "White-winged Dove"),
                     ("eucdov", "Collared-Dove (CONTROL)")):
        ba = anomaly({d: eb[d][sp] or 0.0 for d in shared})
        row = f"{name:<26}"
        for lag in range(-3, 4):
            xs, ys = [], []
            for i, d in enumerate(shared):
                t = (date.fromisoformat(d) + timedelta(days=lag)).isoformat()
                if t in aa:
                    xs.append(aa[t]); ys.append(ba[d])
            c = corr(xs, ys)
            row += (f"{c:+.2f}" if c is not None else "  —").rjust(9)
        print(row)
    print("\nlag +N = dove anomaly N days AFTER the predicted arrival")
    print("PASS looks like: migratory species positive near lag 0, control flat.")


run([int(a) for a in sys.argv[1:]] or None)
