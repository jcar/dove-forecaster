#!/usr/bin/env python3
"""Render the dashboard from committed data. Run after daily.py."""
import json, glob, os

TPL = open("dashboard_template.html").read()

def bundle():
    f = json.load(open(sorted(glob.glob("data/forecasts/*.json"))[-1]))
    eb = {}
    for p in sorted(glob.glob("data/ebird/*.json")):
        d = json.load(open(p))
        if d["n_complete"] >= 5:
            eb[d["date"]] = {s: d["species"][s]["per_hour"] for s in ("moudov","whwdov","eucdov")}
            eb[d["date"]]["n"] = d["n_complete"]
            eb[d["date"]]["h"] = d["checklist_hours"]
    sp = []
    for p in sorted(glob.glob("data/backtest/*.json")):
        sp += [x["speed_mph"] for x in json.load(open(p))["fronts"] if x["speed_mph"]]
    return {"forecast": f, "ebird": eb, "speeds": sorted(sp)}

os.makedirs("docs", exist_ok=True)
open("docs/index.html","w").write(TPL.replace("__DATA__", json.dumps(bundle(), separators=(",",":"))))
print("wrote docs/index.html")
