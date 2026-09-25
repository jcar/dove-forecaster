"""Is the rise in doves MOVING SOUTH? — read from the birds, not the weather.

Two rules, both from the project's own notes:
  * Rows are never compared to each other in absolute terms. DFW has fifty
    reporting stops where Nebraska has four; each latitude is read only
    against its OWN recent past.
  * A propagating anomaly is migration or it is nothing. Birders in Nebraska
    and Texas do not coordinate their weekends.

The payoff: a migration speed measured from bird counts, entirely
independent of the weather model - the first external check on the flight
physics that needs nobody standing in a field.
"""
from statistics import median, mean

ROW_SPACING_MI = 2.5 * 69.0        # wave.ROWS are 2.5 degrees apart
MIN_DAYS_FOR_SPEED = 14


def density(cell):
    """Doves per stop that actually reported a number. Stops logging only
    'X' (present, uncounted) add to locations but not birds, and would
    dilute the ratio."""
    if not cell or not cell.get("counted"):
        return None
    return cell["birds"] / cell["counted"]


def anomaly(values, win=7):
    """Each value minus that row's own centred rolling median. None stays None."""
    out = []
    for i, v in enumerate(values):
        if v is None:
            out.append(None)
            continue
        lo, hi = max(0, i - win // 2), min(len(values), i + win // 2 + 1)
        base = [x for x in values[lo:hi] if x is not None]
        out.append(round(v - median(base), 2) if len(base) >= 3 else None)
    return out


def _corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 5:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return None, len(pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy), len(pairs)


def propagation(rows_north_first, max_lag=6):
    """For each adjacent pair (north row, the row south of it), find the lag
    at which the southern row best echoes the northern one. A consistent
    positive lag is a southward wave; its size gives the speed."""
    pairs = []
    for k in range(len(rows_north_first) - 1):
        north, south = rows_north_first[k], rows_north_first[k + 1]
        best = None
        for lag in range(0, max_lag + 1):
            shifted = [None] * lag + north[:len(north) - lag] if lag else north
            r, n = _corr(shifted, south)
            if r is not None and (best is None or r > best[1]):
                best = (lag, r, n)
        if best:
            pairs.append({"pair": k, "lag_days": best[0],
                          "r": round(best[1], 2), "n": best[2]})
    return pairs


def r_critical(n, lags_searched=7, alpha=0.05):
    """How strong a correlation must be to mean anything.

    We pick the BEST of several lags, so a plain r threshold is fooled by
    chance - on ~14 days a fixed 0.35 bar passed four pairs of NON-migratory
    collared doves. Bonferroni over the lags searched, one-sided (only a
    positive echo counts), via the Fisher z approximation.
    """
    import math
    if n < 6:
        return 1.0
    a = alpha / lags_searched
    # inverse normal tail, rational approximation (Abramowitz-Stegun 26.2.23)
    tt = math.sqrt(-2 * math.log(a))
    z = tt - (2.515517 + 0.802853 * tt + 0.010328 * tt * tt) / \
            (1 + 1.432788 * tt + 0.189269 * tt * tt + 0.001308 * tt ** 3)
    return math.tanh(z / math.sqrt(n - 3))


def summarise(pairs, n_days, control_pairs=None):
    """One honest sentence's worth of numbers, or a refusal."""
    for p in pairs:
        p["r_crit"] = round(r_critical(p["n"]), 2)
        p["passes"] = p["lag_days"] > 0 and p["r"] >= p["r_crit"]
    if n_days < MIN_DAYS_FOR_SPEED:
        return {"status": "thin", "days": n_days,
                "need": MIN_DAYS_FOR_SPEED, "pairs": pairs}
    # The control gate. Collared doves do not migrate; if they pass the SAME
    # test, the "wave" is birders moving, and nothing here can be trusted.
    if control_pairs is not None:
        for p in control_pairs:
            p["r_crit"] = round(r_critical(p["n"]), 2)
            p["passes"] = p["lag_days"] > 0 and p["r"] >= p["r_crit"]
        if sum(p["passes"] for p in control_pairs) >= 2:
            return {"status": "control_fails", "days": n_days, "pairs": pairs}
    good = [p for p in pairs if p["passes"]]
    if len(good) < 2:
        return {"status": "no_wave", "days": n_days, "pairs": pairs}
    lag = median(p["lag_days"] for p in good)
    mph = ROW_SPACING_MI / (lag * 24.0)
    if not 2.0 <= mph <= 60.0:
        return {"status": "implausible", "days": n_days, "pairs": pairs}
    return {"status": "wave", "days": n_days, "lag_days_per_row": lag,
            "mi_per_day": round(ROW_SPACING_MI / lag),
            "implied_mph": round(mph, 1),
            "agreeing_pairs": len(good), "of_pairs": len(pairs),
            "pairs": pairs}
