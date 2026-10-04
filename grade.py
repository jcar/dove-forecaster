#!/usr/bin/env python3
"""Score every flyway's forecasts against what eBird birders actually counted.

This is the rule for publishing a flyway (DECISIONS D24), and it applies to
the Central flyway too, which is published on the strength of one verified
event and nothing more.

For each eBird circle, take the forecast location nearest its centre. Pair
the arrival that location was forecast to get on day D - made 1, 2 or 3 days
earlier - with the circle's mourning-dove count on day D, measured against
that circle's own rolling normal. Correlate per circle, then combine circles
with Fisher's z, weighted by how many days each contributes.

The collared dove is the control. It does not migrate, so a forecast that
"predicts" collared doves too is predicting birders, not birds.

    building    fewer than MIN_DAYS forecast days on record
    passes      mourning-dove skill (z >= Z_PASS) and the control stays quiet
    control     the control correlates as well - we are measuring observers
    no skill    the record is long enough and the forecasts do not track birds

Both flight laws are scored (D21): `arrival` is the live law, `challenger`
the old linear one. Same birds, same wind - the counts pick between them.
"""
import glob
import json
import math
import os
from datetime import date, timedelta

LEADS = (1, 2, 3)
MIN_DAYS = 21              # distinct forecast-target days before any verdict
MAX_KM = 60                # circle centre to its forecast location
Z_PASS = 2.71              # one-sided p < 0.01 after Bonferroni over 3 leads
Z_CONTROL = 1.64           # control "quiet" means not even p < 0.05
OUT = "docs/data/grades.json"


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def corr(xs, ys):
    n = len(xs)
    if n < 6:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def combine(rs):
    """Fisher-z combination of per-circle correlations: [(r, n)] -> z score."""
    num = sum((n - 3) * math.atanh(max(-0.999, min(0.999, r))) for r, n in rs)
    w = sum(n - 3 for _, n in rs)
    return (num / math.sqrt(w)) if w > 0 else None, w


def main():
    if not os.path.exists("docs/data/wave.json"):
        print("no wave.json - run dashboard.py first")
        return 1
    wave = json.load(open("docs/data/wave.json"))
    wdays = {d: i for i, d in enumerate(wave["days"])}

    # forecasts[(site, target_day, lead, law)] = arrival
    logs, sites = {}, {}
    for p in sorted(glob.glob("data/sitelog/*.json")):
        made = date.fromisoformat(os.path.basename(p)[:10])
        d = json.load(open(p))
        for sid, row in d["sites"].items():
            sites[sid] = row
            for law in ("arrival", "challenger"):
                for k, day in enumerate(d["dates"]):
                    lead = (date.fromisoformat(day) - made).days
                    if lead in LEADS:
                        logs[(sid, day, lead, law)] = row[law][k]
    if not sites:
        print("no forecast log yet")
        return 0

    out = {"generated_at": date.today().isoformat(), "flyways": {}}
    for fw in ("central", "mississippi", "atlantic", "pacific"):
        circles = [c for c in wave["map"]["circles"] if c["flyway"] == fw]
        fw_sites = {k: v for k, v in sites.items() if v["flyway"] == fw}
        pairs = []
        for c in circles:
            near = min(fw_sites.items(), key=lambda kv: km((c["lat"], c["lon"]), (kv[1]["lat"], kv[1]["lon"])),
                       default=None)
            if near and km((c["lat"], c["lon"]), (near[1]["lat"], near[1]["lon"])) <= MAX_KM:
                pairs.append((c, near[0]))
        res, target_days = {}, set()
        for law in ("arrival", "challenger"):
            for lead in LEADS:
                per = {"moudov": [], "eucdov": []}
                for c, sid in pairs:
                    for sp in per:
                        xs, ys = [], []
                        for day, i in wdays.items():
                            f = logs.get((sid, day, lead, law))
                            a = c["anomaly"][sp][i]
                            if f is not None and a is not None:
                                xs.append(f); ys.append(a)
                                target_days.add(day)
                        r = corr(xs, ys)
                        if r is not None:
                            per[sp].append((r, len(xs)))
                zm, wm = combine(per["moudov"])
                zc, _ = combine(per["eucdov"])
                res[f"{law}_lead{lead}"] = {"z": None if zm is None else round(zm, 2),
                                            "z_control": None if zc is None else round(zc, 2),
                                            "circles": len(per["moudov"]), "weight": wm}
        n_days = len(target_days)
        live = [res[f"arrival_lead{l}"] for l in LEADS]
        best = max((r for r in live if r["z"] is not None), key=lambda r: r["z"], default=None)
        if n_days < MIN_DAYS or best is None:
            status = "building"
        elif any((r["z_control"] or 0) >= Z_CONTROL for r in live):
            status = "control"
        elif best["z"] >= Z_PASS:
            status = "passes"
        else:
            status = "no_skill"
        law_pick = None
        if status != "building":
            za = sum(res[f"arrival_lead{l}"]["z"] or 0 for l in LEADS)
            zc = sum(res[f"challenger_lead{l}"]["z"] or 0 for l in LEADS)
            law_pick = "live" if za >= zc else "challenger"
        out["flyways"][fw] = {"status": status, "days": n_days, "need_days": MIN_DAYS,
                              "circles_paired": len(pairs), "locations": len(fw_sites),
                              "better_law": law_pick, "scores": res}
        print(f"{fw:12} {status:9} {n_days:3} days, {len(pairs)} circles paired"
              + (f", best z {best['z']}" if best else ""))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
