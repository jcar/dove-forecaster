#!/usr/bin/env python3
"""Rerun the dove forecast "as of" past mornings on observed weather, and
score it the way grade.py scores the live record (D33).

    python hindcast.py --start 2026-09-10 --end 2026-10-07 --cut 2026-10-08

Weather comes from the weather cache (data/wxcache, restored from the
wxcache branch); days before its newest run are observed, so this is the
forecast's best case - it tests the birds, not the weather forecast. The
clock in dove.engine / dove.front is pinned to each as-of morning. Bird data
never enters the forecast.

Scoring uses grade.grade_one on docs/data/wave.json (build it with
dashboard.py first), plus a shift-null: every forecast moved 5-20 days out
of step with the birds. Daily counts are streaky, so Fisher's z alone
overstates significance; a real skill has to beat nearly every shift.

Past seasons need weather the cache no longer holds and eBird checklists the
API cannot supply (F9): they wait on the eBird Basic Dataset and an archive
weather source. Same scorer, different inputs.
"""
import argparse
import contextlib
import glob
import io
import json
import os
from datetime import date, datetime, timedelta
from multiprocessing import Pool

import dove.engine as E
import dove.front as Fr
from dove.flyway import catalogue
from dove.grid import PointCache
from dove.profiles import DOVE_V2

LAWS = ("arrival", "challenger", "dove_v2")
OUT = "data/hindcast"
_C, _SITES = None, None


def load_cache(cache_dir, cut):
    c = PointCache(past_days=2, cache_dir=cache_dir)
    for p in glob.glob(os.path.join(cache_dir, "*.json")):
        lat, lon = map(float, os.path.basename(p)[:-5].split("_"))
        f, ps = c._load_disk((lat, lon))
        c._feat[(lat, lon)] = {d: v for d, v in f.items() if d <= cut}
        c._pass[(lat, lon)] = [(t, s) for t, s in ps if t.date().isoformat() <= cut]
    return c


def _pin(asof):
    frozen = datetime.combine(asof, datetime.min.time()).replace(hour=7)

    class DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen
    E.datetime = DT
    Fr.datetime = DT


def one(asof):
    _pin(asof)
    rows, dates = {}, None
    for s in _SITES:
        try:
            a = E.run((s["lat"], s["lon"]), s["id"], grid=_C, ensemble=None, future=5)
            b = E.run((s["lat"], s["lon"]), s["id"], grid=_C, ensemble=None, future=5, profile=DOVE_V2)
        except Exception:
            continue
        dates = dates or [r["date"] for r in a["arrival"]]
        rows[s["id"]] = {"lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"],
                         "arrival": [r["arrival"] for r in a["arrival"]],
                         "challenger": [r["arrival"] for r in a["arrival_challenger"]["days"]],
                         "dove_v2": [r["arrival"] for r in b["arrival"]]}
    return asof.isoformat(), {"dates": dates, "sites": rows}


def score(run_dir, wave, flyway):
    import grade as G
    logs, sites = {}, {}
    for p in sorted(glob.glob(f"{run_dir}/*.json")):
        made = date.fromisoformat(os.path.basename(p)[:10])
        d = json.load(open(p))
        for sid, row in d["sites"].items():
            sites[sid] = row
            for law in LAWS:
                for k, day in enumerate(d["dates"] or []):
                    lead = (date.fromisoformat(day) - made).days
                    if lead in G.LEADS:
                        logs[(sid, day, lead, law)] = row[law][k]
    spec = dict(G.FORECASTS["dove"], wave=wave)

    def grade(lg):
        with contextlib.redirect_stdout(io.StringIO()):
            return G.grade_one(spec, sites, lg)[flyway]
    real = grade(logs)
    print(f"{flyway}: {real['status']}, {real['days']} days, {real['circles_paired']} circles paired, "
          f"calendar z {real['z_calendar']}")
    null = {law: [] for law in LAWS}
    for k in list(range(-20, -4)) + list(range(5, 21)):
        lg = {(sid, (date.fromisoformat(day) + timedelta(days=k)).isoformat(), lead, law): v
              for (sid, day, lead, law), v in logs.items()}
        r = grade(lg)
        for law in LAWS:
            null[law].append(r["scores"][f"{law}_lead1"]["z"])
    for law in LAWS:
        z = real["scores"][f"{law}_lead1"]["z"]
        zs = [x for x in null[law] if x is not None]
        beat = sum(1 for x in zs if z is not None and x >= z)
        print(f"  {law:11} lead-1 z {z}  control z {real['scores'][f'{law}_lead1']['z_control']}  "
              f"shifts scoring as well: {beat}/{len(zs)}")
    return real, null


def main():
    global _C, _SITES
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--cut", required=True, help="last observed day in the cache")
    ap.add_argument("--flyway", default="central")
    ap.add_argument("--cache-dir", default="data/wxcache")
    ap.add_argument("--wave", default="docs/data/wave.json")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args()
    _C = load_cache(a.cache_dir, a.cut)
    _SITES = catalogue(flyways=[a.flyway])
    run_dir = os.path.join(a.out, f"{a.start}_{a.end}")
    os.makedirs(run_dir, exist_ok=True)
    d0, d1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]
    with Pool(a.workers) as p:                 # fork: workers share the loaded cache
        for asof, rec in p.imap_unordered(one, days):
            json.dump(rec, open(os.path.join(run_dir, f"{asof}.json"), "w"), separators=(",", ":"))
            print(f"  {asof}: {len(rec['sites'])} locations", flush=True)
    score(run_dir, a.wave, a.flyway)


if __name__ == "__main__":
    main()
