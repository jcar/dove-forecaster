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
Z_OVER_CALENDAR = 1.0      # must also beat "the calendar alone" by this much
CALENDAR_DAYS = 21         # the calendar: each circle's own centred 21-day mean
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


# What each forecast is scored on: its log key(s), the eBird species it
# predicts (summed when a group), the wave file those counts live in, and
# which log date list its arrays follow.
FORECASTS = {
    "dove":         {"laws": ("arrival", "challenger", "dove_v2"), "species": ("moudov",),
                     "wave": "docs/data/wave.json", "dates": "dates", "live": "arrival"},
    # ducks (D30): every species on its own, each group, and all ducks together
    **{f"duck_{k}": {"laws": (f"duck_{k}",), "species": (k,), "wave": "docs/data/duck/wave.json",
                     "dates": "duck_dates", "live": f"duck_{k}"}
       for k in ("mallar3", "gnwtea", "buwtea", "gadwal", "amewig", "norpin")},
    "duck_mallard": {"laws": ("duck_mallard",), "species": ("mallar3",),
                     "wave": "docs/data/duck/wave.json", "dates": "duck_dates", "live": "duck_mallard"},
    "duck_teal":    {"laws": ("duck_teal",), "species": ("gnwtea", "buwtea"),
                     "wave": "docs/data/duck/wave.json", "dates": "duck_dates", "live": "duck_teal"},
    "duck_puddle":  {"laws": ("duck_puddle",), "species": ("gadwal", "amewig", "norpin"),
                     "wave": "docs/data/duck/wave.json", "dates": "duck_dates", "live": "duck_puddle"},
    "duck_all":     {"laws": ("duck_all",),
                     "species": ("mallar3", "gnwtea", "buwtea", "gadwal", "amewig", "norpin"),
                     "wave": "docs/data/duck/wave.json", "dates": "duck_dates", "live": "duck_all"},
}
CONTROL = "eucdov"


def circle_anomaly(c, species):
    """A circle's anomaly for a species GROUP: pooled density (birds per
    counting stop across the group), then minus the circle's own rolling
    median - the same rule as the published heatmaps."""
    from dove.wavetrend import anomaly
    n = len(c["birds"][species[0]])
    dens = []
    for i in range(n):
        b = sum(c["birds"][s][i] or 0 for s in species if s in c["birds"])
        k = sum(c["counted"][s][i] or 0 for s in species if s in c["counted"])
        dens.append(b / k if k else None)
    return anomaly(dens)


def grade_one(spec, sites, logs):
    if not os.path.exists(spec["wave"]):
        return None
    wave = json.load(open(spec["wave"]))
    wdays = {d: i for i, d in enumerate(wave["days"])}
    out = {}
    for fw in ("central", "mississippi", "atlantic", "pacific"):
        circles = [c for c in wave["map"]["circles"] if c["flyway"] == fw]
        fw_sites = {k: v for k, v in sites.items() if v["flyway"] == fw}
        pairs = []
        for c in circles:
            near = min(fw_sites.items(), key=lambda kv: km((c["lat"], c["lon"]), (kv[1]["lat"], kv[1]["lon"])),
                       default=None)
            if near and km((c["lat"], c["lon"]), (near[1]["lat"], near[1]["lon"])) <= MAX_KM:
                pairs.append((c, near[0], circle_anomaly(c, spec["species"]),
                              circle_anomaly(c, (CONTROL,)) if CONTROL in c["birds"] else None))
        # THE CALENDAR (BirdCast's lesson): a forecast that knows only the
        # season's slow shape. Built from each circle's own 21-day centred
        # mean - which peeks at the future, so it is a generous calendar and
        # a strict bar. Skill means beating it, not beating zero.
        cal = []
        for c, sid, an_t, an_c in pairs:
            n = len(an_t)
            sp_ = spec["species"]
            dens = []
            for i in range(n):
                b = sum(c["birds"][x][i] or 0 for x in sp_ if x in c["birds"])
                k = sum(c["counted"][x][i] or 0 for x in sp_ if x in c["counted"])
                dens.append(b / k if k else None)
            h = CALENDAR_DAYS // 2
            sm = [None if dens[i] is None else
                  (lambda w: sum(w) / len(w) if w else None)(
                      [x for x in dens[max(0, i - h):i + h + 1] if x is not None]) for i in range(n)]
            xs = [sm[i] for i in range(n) if sm[i] is not None and an_t[i] is not None]
            ys = [an_t[i] for i in range(n) if sm[i] is not None and an_t[i] is not None]
            r = corr(xs, ys)
            if r is not None:
                cal.append((r, len(xs)))
        z_cal, _ = combine(cal)
        res, target_days = {}, set()
        for law in spec["laws"]:
            for lead in LEADS:
                per_t, per_c = [], []
                for c, sid, an_t, an_c in pairs:
                    for an, per in ((an_t, per_t), (an_c, per_c)):
                        if an is None:
                            continue
                        xs, ys = [], []
                        for day, i in wdays.items():
                            f = logs.get((sid, day, lead, law))
                            if f is not None and an[i] is not None:
                                xs.append(f); ys.append(an[i])
                                if per is per_t:
                                    target_days.add(day)
                        r = corr(xs, ys)
                        if r is not None:
                            per.append((r, len(xs)))
                zm, wm = combine(per_t)
                zc, _ = combine(per_c)
                res[f"{law}_lead{lead}"] = {"z": None if zm is None else round(zm, 2),
                                            "z_control": None if zc is None else round(zc, 2),
                                            "circles": len(per_t), "weight": wm}
        n_days = len(target_days)
        live = [res[f"{spec['live']}_lead{l}"] for l in LEADS]
        best = max((r for r in live if r["z"] is not None), key=lambda r: r["z"], default=None)
        if n_days < MIN_DAYS or best is None:
            status = "building"
        elif any((r["z_control"] or 0) >= Z_CONTROL for r in live):
            status = "control"
        elif best["z"] >= Z_PASS and best["z"] >= (z_cal or 0) + Z_OVER_CALENDAR:
            status = "passes"
        else:
            status = "no_skill"
        laws = {law: round(sum(res[f"{law}_lead{l}"]["z"] or 0 for l in LEADS), 2)
                for law in spec["laws"]}
        out[fw] = {"status": status, "days": n_days, "need_days": MIN_DAYS,
                   "z_calendar": None if z_cal is None else round(z_cal, 2),
                   "circles_paired": len(pairs), "locations": len(fw_sites),
                   "best_law": max(laws, key=laws.get) if status != "building" else None,
                   "law_scores": laws if status != "building" else None, "scores": res}
        print(f"  {spec['live']:14} {fw:12} {status:9} {n_days:3} days, {len(pairs)} circles"
              + (f", best z {best['z']}" if best else "")
              + (f", calendar z {z_cal:.2f}" if z_cal is not None else ""))
    return out


def main():
    logs, sites = {}, {}
    for p in sorted(glob.glob("data/sitelog/*.json")):
        made = date.fromisoformat(os.path.basename(p)[:10])
        d = json.load(open(p))
        for sid, row in d["sites"].items():
            sites[sid] = row
            for spec in FORECASTS.values():
                ds = d.get(spec["dates"]) or []
                for law in spec["laws"]:
                    arr = row.get(law)
                    if not arr:
                        continue
                    for k, day in enumerate(ds[:len(arr)]):
                        lead = (date.fromisoformat(day) - made).days
                        if lead in LEADS:
                            logs[(sid, day, lead, law)] = arr[k]
    if not sites:
        print("no forecast log yet")
        return 0
    out = {"generated_at": date.today().isoformat(), "forecasts": {}}
    for key, spec in FORECASTS.items():
        g = grade_one(spec, sites, logs)
        if g is not None:
            out["forecasts"][key] = g
    out["flyways"] = out["forecasts"].get("dove", {})       # the page's dove scorecard
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
