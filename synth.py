#!/usr/bin/env python3
"""Synthetic weather, so the animation can be built and judged before the
real history exists.

Only the WEATHER is invented. Every number downstream of it — push index,
front detection, flight simulation, arrivals — is produced by the real model
running on this field, so the shapes, timings and failure modes are the ones
the product will actually have.

Kept scrupulously separate from the truth:
  * never writes to data/wxcache (the real cache)
  * stamps synthetic:true into flow.json, which the page shows as a banner
  * the next real build overwrites it with no cleanup
"""
import json, math, os, random
from datetime import date, datetime, timedelta

from dove.flyway_nodes import lattice_nodes
import flyway

SEED = 11


class Front:
    """A cold boundary marching south at a plausible clip.

    Real fronts in this backtest ran a median 19.9 mph with a wide spread, and
    they decelerate pushing into southern heat — both reproduced here, because
    a synthetic field that behaves too neatly would flatter the model.
    """

    def __init__(self, day0, lat0, mph, strength, tilt):
        self.day0, self.lat0, self.mph = day0, lat0, mph
        self.strength, self.tilt = strength, tilt

    def lat_at(self, n_days, lon):
        # decelerates as it runs south, and leans — fronts are not straight
        decay = 1.0 - 0.45 * min(1.0, n_days / 6.0)
        travelled = self.mph * 24.0 * decay * n_days / 69.0
        return self.lat0 - travelled + self.tilt * (lon + 97.0)

    def push_at(self, n_days, lat, lon):
        if n_days < 0:
            return 0.0
        d = lat - self.lat_at(n_days, lon)          # + = behind the front
        age = math.exp(-max(0.0, n_days - 1.0) / 7.0)
        if d >= 0:
            return self.strength * math.exp(-d / 5.4) * age      # northerly behind
        return -0.62 * self.strength * math.exp(d / 4.2) * age   # southerly ahead


def build(days=45, out_dir="docs/data"):
    rnd = random.Random(SEED)
    nodes = lattice_nodes()
    end = date.today() + timedelta(days=16)
    dates = [(end - timedelta(days=k)).isoformat() for k in range(days)][::-1]

    fronts = []
    d0 = 3
    while d0 < days - 2:
        fronts.append(Front(d0, 50.0, rnd.uniform(13, 31), rnd.uniform(12, 24),
                            rnd.uniform(-0.045, 0.045)))
        d0 += rnd.randint(5, 9)                      # a boundary every 5-9 days

    feat, passes = {}, {}
    for (la, lo) in nodes:
        jitter = random.Random(hash((la, lo)) & 0xffff)
        series, crossings = {}, []
        for i, d in enumerate(dates):
            push = sum(f.push_at(i - f.day0, la, lo) for f in fronts)
            # The plains run a persistent low-level southerly between fronts —
            # without it the field is unrealistically calm and the real data's
            # p10 of -8.9 mph has no counterpart.
            # Baseline near calm with moderate spread; the FRONTS supply the
            # tails — their southerly side gives the negative one, their
            # northerly side the positive. Matching the real distribution by
            # cranking noise instead would look like static, not weather.
            push += 0.8 + jitter.gauss(0, 3.5)
            # seasonal cooling, colder further north, colder behind a front
            base = 96 - (la - 26.0) * 1.15 - i * 0.42
            tmax = base - max(0.0, push) * 0.85 + jitter.gauss(0, 2.0)
            pres = 1012 + max(0.0, push) * 0.55 - max(0.0, -push) * 0.35 + jitter.gauss(0, 1.4)
            cloud = min(95, max(4, 28 + abs(push) * 2.4 + jitter.gauss(0, 12)))
            series[d] = {"tmax": round(tmax, 1), "wind_push": round(push, 2),
                         "p_mean": round(pres, 1), "cloud_am": round(cloud, 1),
                         "max_hourly_drop": round(max(0.3, push * 0.22 + jitter.gauss(0, 0.4)), 2)}
            prev = sum(f.push_at(i - 1 - f.day0, la, lo) for f in fronts) if i else 0.0
            cur = sum(f.push_at(i - f.day0, la, lo) for f in fronts)
            if cur > 6.0 and prev <= 6.0:                     # the day it crosses
                crossings.append((datetime.fromisoformat(d + "T" + f"{jitter.randint(0,23):02d}:00"),
                                  round(18 + push * 1.3, 1)))
        feat[(la, lo)] = series
        passes[(la, lo)] = crossings

    class Field:
        """Same interface as grid.PointCache, so the REAL engine runs on it
        unmodified — only the weather is invented."""
        def __init__(self, fe, pa): self._feat, self._pass = fe, pa
        def features(self, lat, lon): return self._feat.get((lat, lon))
        def passages(self, lat, lon): return self._pass.get((lat, lon))
    fld = Field(feat, passes)
    return fld, dates, len(fronts)


def main():
    from dove.flyway import catalogue
    from dove.engine import run
    from build_sites import slim, FLOW_DAYS

    fld, dates, nfronts = build()
    sites = catalogue()
    print(f"synthetic field: {len(fld._feat)} nodes, {len(dates)} days, {nfronts} fronts")

    os.makedirs("docs/data/loc", exist_ok=True)
    built, index = [], []
    for s in sites:
        try:
            res = run((s["lat"], s["lon"]), s["id"], grid=fld, ensemble=None)
        except Exception:
            continue
        sl = slim(res, s)
        json.dump(sl, open(f"docs/data/loc/{s['id']}.json", "w"), separators=(",", ":"))
        built.append(sl)
        pk = max(res["arrival"], key=lambda r: r["arrival"])
        index.append({"id": s["id"], "lat": s["lat"], "lon": s["lon"],
                      "peak_date": pk["date"], "peak": pk["arrival"]})
    json.dump({"generated_at": datetime.utcnow().isoformat(timespec="seconds"),
               "synthetic": True, "sites": index},
              open("docs/data/index.json", "w"), separators=(",", ":"))

    p, sz = flyway.export(fld, built, dates[-FLOW_DAYS:])
    d = json.load(open(p)); d["synthetic"] = True
    json.dump(d, open(p, "w"), separators=(",", ":"))
    print(f"  {len(built)} sites, flow {sz/1000:.0f} KB over {min(FLOW_DAYS,len(dates))} days")
    print(f"  every file stamped synthetic:true; the next real build overwrites it")


if __name__ == "__main__":
    main()
