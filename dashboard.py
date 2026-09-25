#!/usr/bin/env python3
"""Render the shell. Data is fetched by the page, not baked into it."""
import json, glob, os, shutil

TPL = "dashboard_template.html"
OUT = "docs"

os.makedirs(f"{OUT}/data", exist_ok=True)
shutil.copyfile(TPL, f"{OUT}/index.html")

# Flyway dove counts BY LATITUDE (see D20). This block used to sum every
# circle into one bucket - it loaded each circle's coordinates and then never
# keyed on them - which erased the only thing the panel exists to show.
from dove.wavetrend import density, anomaly, propagation, summarise

newest = {}                                    # (circle, species, day) -> cell
circles = {}
for p in sorted(glob.glob("data/wave/*.json")):     # sorted = oldest first...
    d = json.load(open(p))
    circles.update(d["circles"])
    for circle, sp in d["counts"].items():
        for s, days in sp.items():
            for day, v in days.items():
                # ...so the newest snapshot of a day wins. Snapshots overlap by
                # a week; summing them counted one day up to eight times, and
                # the recent edge fewer times than the middle.
                newest[(circle, s, day)] = v

rows = sorted({c["lat"] for c in circles.values()})
all_days = sorted({k[2] for k in newest})
species = ["moudov", "whwdov", "eucdov"]
series, anom, prop = {}, {}, {}
for s in species:
    per_row = []
    for lat in rows:
        names = [n for n, c in circles.items() if c["lat"] == lat]
        vals = []
        for day in all_days:
            # the three longitude columns ARE one latitude; pooling them is the
            # intended sampling. Pooling ACROSS latitudes was the bug.
            b = sum(newest.get((n, s, day), {}).get("birds", 0) for n in names)
            c = sum(newest.get((n, s, day), {}).get("counted", 0) for n in names)
            vals.append(density({"birds": b, "counted": c}))
        per_row.append(vals)
    series[s] = [[None if v is None else round(v, 2) for v in r] for r in per_row]
    anom[s] = [anomaly(r) for r in per_row]
    prop[s] = propagation(list(reversed(anom[s])))
ctrl = prop["eucdov"]
prop = {s: summarise(prop[s], len(all_days),
                     control_pairs=None if s == "eucdov" else [dict(p) for p in ctrl])
        for s in species}

json.dump({"rows": rows, "days": all_days, "series": series,
           "anomaly": anom, "propagation": prop},
          open(f"{OUT}/data/wave.json", "w"), separators=(",", ":"))

# front-speed distribution from the backtest, for the trust panel
speeds = []
for p in sorted(glob.glob("data/backtest/*.json")):
    speeds += [x["speed_mph"] for x in json.load(open(p))["fronts"] if x["speed_mph"]]
json.dump({"speeds": sorted(speeds)}, open(f"{OUT}/data/backtest.json", "w"),
          separators=(",", ":"))
print(f"wrote {OUT}/index.html + wave ({len(all_days)} days x {len(rows)} rows) + backtest ({len(speeds)} fronts)")
