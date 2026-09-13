#!/usr/bin/env python3
"""Render the shell. Data is fetched by the page, not baked into it."""
import json, glob, os, shutil

TPL = "dashboard_template.html"
OUT = "docs"

os.makedirs(f"{OUT}/data", exist_ok=True)
shutil.copyfile(TPL, f"{OUT}/index.html")

# flyway-wide dove counts, shared by every visitor (see D14)
wave = {}
for p in sorted(glob.glob("data/wave/*.json")):
    d = json.load(open(p))
    for circle, sp in d["counts"].items():
        c = d["circles"].get(circle)
        if not c:
            continue
        for s, days in sp.items():
            for day, v in days.items():
                wave.setdefault(day, {}).setdefault(s, {"birds": 0, "locations": 0})
                wave[day][s]["birds"] += v["birds"]
                wave[day][s]["locations"] += v["locations"]
json.dump({"days": wave}, open(f"{OUT}/data/wave.json", "w"), separators=(",", ":"))

# front-speed distribution from the backtest, for the trust panel
speeds = []
for p in sorted(glob.glob("data/backtest/*.json")):
    speeds += [x["speed_mph"] for x in json.load(open(p))["fronts"] if x["speed_mph"]]
json.dump({"speeds": sorted(speeds)}, open(f"{OUT}/data/backtest.json", "w"),
          separators=(",", ":"))
print(f"wrote {OUT}/index.html + wave ({len(wave)} days) + backtest ({len(speeds)} fronts)")
