#!/usr/bin/env python3
"""Render the shell. Data is fetched by the page, not baked into it."""
import json, glob, os, shutil

TPL = "dashboard_template.html"
OUT = "docs"

os.makedirs(f"{OUT}/data", exist_ok=True)
shutil.copyfile(TPL, f"{OUT}/index.html")

# Flyway dove counts (D20, D22). Every circle is read against ITS OWN rolling
# median; rows and flyways are built from those per-circle anomalies, never by
# pooling raw counts - pooling breaks the day a new circle joins a row, and
# the national grid (2026-10-04) added ~100 circles with no history.
from dove.wavetrend import density, anomaly, propagation, summarise
from dove.regions import nearest_flyway, FLYWAY_NAME
from flyway import albers_box_fit_us, build_geo_us
import flyway as _fw
build_geo_us()          # geometry is rebuilt each run: docs/ is not committed
_fw.build_geo(_fw.GEO_SRC)

KEEP_DAYS = 45
species = ["moudov", "whwdov", "eucdov"]

# One record per location per pull (eBird returns each spot's LATEST
# sighting), so overlapping pulls are UNIONED by (location, day) where the
# records exist, and otherwise the pull that saw a day at the most locations
# wins. "Newest pull wins" - the rule until 2026-10-04 - drops every hotspot
# that was birded again later.
recs = {}                                      # (circle, sp) -> {(loc, day): howMany}
legacy = {}                                    # (circle, sp, day) -> best aggregate cell
circles, first_pull, run_dates = {}, {}, []
for p in sorted(glob.glob("data/wave/*.json")):
    d = json.load(open(p))
    run_dates.append(d["run_date"])
    circles.update(d["circles"])
    for c in d["circles"]:
        first_pull.setdefault(c, d["run_date"])
    for circle, sp in d.get("records", {}).items():
        for s_, rows_ in sp.items():
            bucket = recs.setdefault((circle, s_), {})
            for loc, day, n in rows_:
                bucket[(loc, day)] = n
    for circle, sp in d["counts"].items():
        for s_, days in sp.items():
            for day, v in days.items():
                k = (circle, s_, day)
                if k not in legacy or v.get("locations", 0) > legacy[k].get("locations", 0):
                    legacy[k] = v

cells = dict(legacy)
for (circle, s_), bucket in recs.items():
    agg = {}
    for (loc, day), n in bucket.items():
        c = agg.setdefault(day, {"birds": 0, "locations": 0, "counted": 0})
        c["locations"] += 1
        if n is not None:
            c["birds"] += int(n)
            c["counted"] += 1
    for day, c in agg.items():
        k = (circle, s_, day)
        if k not in cells or c["locations"] >= cells[k].get("locations", 0):
            cells[k] = c

# A circle's very first pull reaches back a week, but sees each spot only on
# its LATEST visit, so the older days in it are short - a fake rising trend.
# Trust a day only from the day before the circle was first pulled.
from datetime import date as _date, timedelta as _td
for k in list(cells):
    start = first_pull.get(k[0])
    if start and k[2] < (_date.fromisoformat(start) - _td(days=1)).isoformat():
        del cells[k]

# Today is never complete at build time (the job runs at 7am), and a half-
# counted day reads as a crash. The page says "counts end yesterday"; make it so.
newest_pull = max(run_dates, default="9999-12-31")
all_days = sorted({k[2] for k in cells if k[2] < newest_pull})[-KEEP_DAYS:]
fit = albers_box_fit_us()
spots = []
for name, c in sorted(circles.items(), key=lambda kv: (-kv[1]["lat"], kv[1]["lon"])):
    fw = nearest_flyway(c["lat"], c["lon"])
    if not fw:
        continue
    x, y = fit(c["lat"], c["lon"])
    _, y2 = fit(c["lat"] + 50 / 111.0, c["lon"])
    spot = {"id": name, "lat": c["lat"], "lon": c["lon"], "flyway": fw,
            "xy": [round(x, 1), round(y, 1)], "r": round(abs(y - y2), 1),
            "birds": {}, "counted": {}, "anomaly": {}}
    for s_ in species:
        cs = [cells.get((name, s_, day)) for day in all_days]
        spot["birds"][s_] = [c_["birds"] if c_ else None for c_ in cs]
        spot["counted"][s_] = [c_["counted"] if c_ else None for c_ in cs]
        spot["anomaly"][s_] = anomaly([density(c_) for c_ in cs])
    spots.append(spot)


def row_mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 2) if v else None


flyways = {}
for fw in FLYWAY_NAME:
    mine = [sp for sp in spots if sp["flyway"] == fw]
    rows = sorted({sp["lat"] for sp in mine})
    anom, prop = {}, {}
    for s_ in species:
        anom[s_] = [[row_mean([sp["anomaly"][s_][i] for sp in mine if sp["lat"] == lat])
                     for i in range(len(all_days))] for lat in rows]
        prop[s_] = propagation(list(reversed(anom[s_])))
    ctrl = prop["eucdov"]
    prop = {s_: summarise(prop[s_], len(all_days),
                          control_pairs=None if s_ == "eucdov" else [dict(q) for q in ctrl])
            for s_ in species}
    flyways[fw] = {"name": FLYWAY_NAME[fw], "rows": rows, "anomaly": anom,
                   "propagation": prop,
                   "circles_per_row": [sum(1 for sp in mine if sp["lat"] == lat) for lat in rows]}

json.dump({"days": all_days, "species": species, "flyways": flyways,
           "map": {"w": fit.w, "h": fit.h, "radius_km": 50, "circles": spots}},
          open(f"{OUT}/data/wave.json", "w"), separators=(",", ":"))
rows = flyways["central"]["rows"]

# front-speed distribution from the backtest, for the trust panel
speeds = []
for p in sorted(glob.glob("data/backtest/*.json")):
    speeds += [x["speed_mph"] for x in json.load(open(p))["fronts"] if x["speed_mph"]]
json.dump({"speeds": sorted(speeds)}, open(f"{OUT}/data/backtest.json", "w"),
          separators=(",", ":"))
print(f"wrote {OUT}/index.html + wave ({len(all_days)} days x {len(rows)} rows) + backtest ({len(speeds)} fronts)")
