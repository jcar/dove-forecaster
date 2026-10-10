"""Duck migration as a population field on the weather lattice (D27).

Doves are forecast per hunter, from four bands north of them. Ducks are
different enough - nocturnal, 300-500+ miles a night, leaving when their own
water freezes - that the right model is the whole continent at once:

  every lattice node holds a relative number of each duck group;
  each night, a share of them leaves:   readiness(node's own freeze/snow)
                                         x night gate(wind aloft, rain, cloud);
  the leavers fly one night south along their flyway's route, a distance
  that grows with how hard the cold came (Pearse et al. 2023), and settle
  across the nodes around where that distance lands them.

So a hard freeze in North Dakota fills Kansas and Nebraska first, and Texas
only on the next push - the cascade, emergent rather than hard-coded. A
hunter's forecast is the birds settling on their node at dawn.

The field must remember the whole season (a December forecast depends on
what October and November already moved), but the weather cache keeps only
40 days. So the field's state is checkpointed to git each morning
(data/duckstate/) a few days back, where the weather is settled, and each
run replays forward from it.

Every parameter is a literature prior (dove/profiles.py); the scorecard
refits them. This is a first model, published with an "untested" label.
"""
import json
import math
import os
from datetime import date, timedelta

from .freeze import wsi_series
from .grid import LAT_STEP, LON_STEP, snap
from .profiles import DUCK_SPECIES as DUCK_GROUPS, NIGHT_GATE   # D30: run per species

STATE_DIR = "data/duckstate"
CHECKPOINT_LAG = 3          # days back, where analysis has settled
QUANTILES = (-1.335, -0.748, -0.385, 0.0, 0.385, 0.748, 1.335)   # 7 equal-mass normal points
SIGMA = 0.35                # log-normal spread of one night's distance
MAX_HOURS = 11.0            # a long autumn night's flight


def _sig(x):
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, x))))


def _theta(g, lat):
    pts = g.theta
    if lat <= pts[0][0]:
        return pts[0][1]
    for (a, ta), (b, tb) in zip(pts, pts[1:]):
        if a <= lat <= b:
            return ta + (tb - ta) * (lat - a) / (b - a)
    return pts[-1][1]


def readiness(g, lat, doy, sev):
    """Share of a node's birds willing to go tonight if the night allows."""
    m = sev.get(g.measure) if sev else None
    r = 0.0 if m is None else _sig((m - _theta(g, lat)) / g.slope)
    if g.calendar_peak_doy is not None:
        peak = g.calendar_peak_doy + 2.0 * (45.0 - lat)
        r = max(r, math.exp(-0.5 * ((doy - peak) / g.calendar_width_d) ** 2))
    return r


_B0 = (math.log(NIGHT_GATE["p_all"] / (1 - NIGHT_GATE["p_all"]))
       - math.log(NIGHT_GATE["or_wind"]) - math.log(NIGHT_GATE["or_dry"])
       - math.log(NIGHT_GATE["or_clear"]))


def night_gate(f, push_key="night_push"):
    """O'Neal et al. 2018: P(departure tonight) from wind aloft, rain, cloud."""
    if not f or f.get(push_key) is None:
        return 0.0
    fw = max(0.0, min(1.0, f[push_key] / NIGHT_GATE["wind_full_mph"]))
    dry = 1.0 if (f.get("night_rain_mm") or 0.0) < NIGHT_GATE["rain_mm"] else 0.0
    clear = 1.0 if (f.get("night_cloud") if f.get("night_cloud") is not None else 0) \
        < NIGHT_GATE["overcast_pct"] else 0.0
    return _sig(_B0 + math.log(NIGHT_GATE["or_wind"]) * fw
                + math.log(NIGHT_GATE["or_dry"]) * dry
                + math.log(NIGHT_GATE["or_clear"]) * clear)


class Field:
    """The lattice, its routes, and one season's replay for every group."""

    def __init__(self, cache, routes):
        self.feat = {pt: f for pt, f in cache._feat.items() if f}
        self.nodes = set(self.feat)
        self.sev = {pt: wsi_series(f) for pt, f in self.feat.items()}
        self.routes = routes        # node -> (bearing deg, push key)

    def _dest(self, pt, miles, bearing):
        lat, lon = pt
        b = math.radians(bearing)
        la = lat - miles * math.cos(b) / 69.0
        lo = lon - miles * math.sin(b) / (69.0 * math.cos(math.radians(lat)))
        q = snap(la, lo)
        if q in self.nodes:
            return q
        for dla in (0, LAT_STEP, -LAT_STEP):          # the lattice has holes (water, borders)
            for dlo in (0, LON_STEP, -LON_STEP):
                r = (round(q[0] + dla, 4), round(q[1] + dlo, 4))
                if r in self.nodes:
                    return r
        return None                                   # flew off the lattice: wintering beyond

    def start_date(self, frac=0.8, deep=21):
        """Earliest day that most nodes WITH a deep duck-weather history
        (>= `deep` days of it) share. Nodes still waiting for the backfill
        hold their birds until their history arrives - they can't be read,
        so they don't launch flocks."""
        firsts = []
        for f in self.feat.values():
            dd = sorted(d for d, v in f.items() if "night_push" in v and "tmean_c" in v)
            if len(dd) >= deep:
                firsts.append(dd[0])
        if not firsts:
            return None
        firsts.sort()
        return firsts[min(len(firsts) - 1, int(frac * len(firsts)))]

    def initial(self, g):
        """Season-start distribution: concentrated on the northern staging
        and breeding grounds (prairie potholes ~45-55 N)."""
        return {pt: 100.0 * _sig((pt[0] - g.north_centre) / 2.0) for pt in self.nodes}

    def run(self, g, start, end, pop=None):
        """Replay nights start..end-1. Returns (pop at the morning of `end`,
        arrivals {date: {node: birds}}, ground {date: {node: birds}},
        ready {date: {node: readiness}})."""
        pop = dict(pop) if pop else self.initial(g)
        arrivals, ground, ready = {}, {}, {}
        d = date.fromisoformat(start)
        stop = date.fromisoformat(end)
        while d < stop:
            di = d.isoformat()
            doy = d.timetuple().tm_yday
            nxt = (d + timedelta(days=1)).isoformat()
            moved, arr, rd = {}, {}, {}
            for pt, n in pop.items():
                f = self.feat[pt].get(di)
                sev = self.sev[pt].get(di)
                r = readiness(g, pt[0], doy, sev)
                rd[pt] = round(r, 3)
                if n <= 0.01 or not f:
                    continue
                bearing, pk = self.routes.get(pt, (0.0, "night_push"))
                leave = n * min(0.9, r * night_gate(f, pk))
                if leave <= 0.001:
                    continue
                # Pearse et al. 2023: farther the harder the cold came
                prev = self.feat[pt].get((d - timedelta(days=1)).isoformat()) or {}
                drop = max(0.0, (prev.get("tmin_c", f.get("tmin_c", 0.0)) or 0.0)
                           - (f.get("tmin_c") or 0.0))
                km = min(g.night_km + g.km_per_c_drop * drop, g.groundspeed_kmh * MAX_HOURS)
                moved[pt] = moved.get(pt, 0.0) - leave
                for z in QUANTILES:
                    miles = km * math.exp(SIGMA * z) / 1.609
                    q = self._dest(pt, miles, bearing)
                    if q is None:
                        continue
                    share = leave / len(QUANTILES)
                    moved[q] = moved.get(q, 0.0) + share
                    arr[q] = arr.get(q, 0.0) + share
            for pt, dv in moved.items():
                pop[pt] = max(0.0, pop.get(pt, 0.0) + dv)
            arrivals[nxt], ready[di] = arr, rd
            ground[nxt] = {pt: round(v, 2) for pt, v in pop.items() if v > 0.05}
            d += timedelta(days=1)
        return pop, arrivals, ground, ready

    def freeze_line(self, ready_day, threshold=0.5):
        """Per longitude column: the southernmost latitude where mallards are
        ready to leave - the duck counterpart of the front line."""
        cols = {}
        for (la, lo), r in ready_day.items():
            if r >= threshold:
                cols[lo] = min(cols.get(lo, 99.0), la)
        return {lo: la for lo, la in sorted(cols.items())}


def load_checkpoint():
    p = os.path.join(STATE_DIR, "state.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    d["groups"] = {k: {tuple(map(float, n.split("_"))): v for n, v in g.items()}
                   for k, g in d["groups"].items()}
    return d


def save_checkpoint(day, pops):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"date": day,
               "groups": {k: {f"{p[0]}_{p[1]}": round(v, 3) for p, v in g.items() if v > 0.001}
                          for k, g in pops.items()}},
              open(os.path.join(STATE_DIR, "state.json"), "w"), separators=(",", ":"))


def season(cache, routes, today=None, horizon=15):
    """Replay every group from the checkpoint (or the earliest day with duck
    weather) through the forecast horizon. Saves a new checkpoint
    CHECKPOINT_LAG days back. Returns per-group results."""
    today = today or date.today()
    F = Field(cache, routes)
    ck = load_checkpoint()
    first = F.start_date()
    if first is None:
        raise RuntimeError("no duck weather features in the cache yet")
    days = sorted({d for f in F.feat.values() for d in f})
    end = days[-1]
    ck_day = (today - timedelta(days=CHECKPOINT_LAG)).isoformat()
    out, new_ck = {}, {}
    for key, g in DUCK_GROUPS.items():
        if ck and ck["date"] >= first and key in ck["groups"]:
            # a checkpoint can hold nodes the lattice no longer carries (D36)
            start, pop = ck["date"], {pt: v for pt, v in ck["groups"][key].items() if pt in F.nodes}
        else:
            start, pop = first, None
        if start < ck_day:
            pop_ck, a1, g1, r1 = F.run(g, start, ck_day, pop)
            pop_end, a2, g2, r2 = F.run(g, ck_day, end, pop_ck)
            a1.update(a2); g1.update(g2); r1.update(r2)
            arrivals, ground, ready = a1, g1, r1
            new_ck[key] = pop_ck
        else:
            # nothing settled to checkpoint yet - keep the existing one
            pop_end, arrivals, ground, ready = F.run(g, start, end, pop)
        out[key] = {"arrivals": arrivals, "ground": ground, "ready": ready,
                    "start": start}
    if new_ck and len(new_ck) == len(DUCK_GROUPS):
        save_checkpoint(ck_day, new_ck)
    out["_field"] = F
    return out
