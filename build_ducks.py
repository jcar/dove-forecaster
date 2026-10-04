#!/usr/bin/env python3
"""Duck forecasts for every location, from the population field (D27).

Called by build_sites.py with the weather cache it already loaded, so ducks
cost no extra weather download. Writes:
  docs/data/duck/index.json        published locations + strength scale
  docs/data/duck/loc/{id}.json     per-location forecast, all three groups
  docs/data/duck/flow.json         freeze line and snow by day, for the map
and returns rows for the forecast log (data/sitelog/) that grade.py scores.
"""
import json
import os
import time
from datetime import date, timedelta

from dove.duck import season
from dove.geo import ROUTES
from dove.grid import snap
from dove.profiles import DUCK_GROUPS
from dove.regions import nearest_flyway

OUT = "docs/data/duck"
SHOW_PAST = 7          # days of history on each chart, for context
SHOW_NEXT = 14


def routes_for(cache):
    out = {}
    for pt in cache._feat:
        fw = nearest_flyway(*pt, reach_deg=3.0) or "central"
        b = ROUTES[fw]["bearing"]
        out[pt] = (b, f"night_push_{int(b)}" if b else "night_push")
    return out


def build(cache, sites, every, us_fit=None, flow_fit=None):
    t0 = time.time()
    res = season(cache, routes_for(cache))
    F = res.pop("_field")
    today = date.today()
    days = [(today + timedelta(days=k)).isoformat() for k in range(-SHOW_PAST, SHOW_NEXT)]
    nxt = days[SHOW_PAST:]
    os.makedirs(f"{OUT}/loc", exist_ok=True)
    pub_ids = {s["id"] for s in sites}
    for f in os.listdir(f"{OUT}/loc"):
        if f[:-5] not in pub_ids:
            os.remove(f"{OUT}/loc/{f}")

    mall_ready = res["duck_mallard"]["ready"]
    log_rows, index = {}, []
    for s in every:
        node = snap(s["lat"], s["lon"])
        groups = {}
        for key, g in DUCK_GROUPS.items():
            r = res[key]
            groups[key] = {
                "name": g.name,
                "arrival": [{"date": d, "arrival": round(r["arrivals"].get(d, {}).get(node, 0.0), 2)}
                            for d in days],
                "ground": [round(r["ground"].get(d, {}).get(node, 0.0), 1) for d in days],
            }
        log_rows.setdefault(s["id"], {"lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"],
                                      "published": s["id"] in pub_ids})
        for key in DUCK_GROUPS:
            log_rows[s["id"]][key] = [a["arrival"] for a in groups[key]["arrival"][SHOW_PAST:]]
        if s["id"] not in pub_ids:
            continue
        sev = F.sev.get(node, {})
        feats = F.feat.get(node, {})
        # how far south mallard-moving cold reaches, in this site's column
        line = []
        for d in days:
            rd = mall_ready.get(d, {})
            col = [pt[0] for pt, v in rd.items() if abs(pt[1] - node[1]) < 0.01 and v >= 0.5]
            line.append(min(col) if col else None)
        payload = {
            "id": s["id"], "lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "untested": True, "dates": days, "today_index": SHOW_PAST,
            "groups": groups,
            "freeze": {"wsi": [sev.get(d, {}).get("wsi") for d in days],
                       "tmean_c": [feats.get(d, {}).get("tmean_c") for d in days],
                       "snow_cm": [feats.get(d, {}).get("snow_cm") for d in days],
                       "line_lat": line},
            "fronts": [t.isoformat(timespec="minutes") for t, _ in (cache._pass.get(node) or [])
                       if t.date().isoformat() >= days[0]],
        }
        json.dump(payload, open(f"{OUT}/loc/{s['id']}.json", "w"), separators=(",", ":"))
        peaks = {k: max(groups[k]["arrival"][SHOW_PAST:], key=lambda a: a["arrival"]) for k in groups}
        index.append({"id": s["id"], "lat": s["lat"], "lon": s["lon"],
                      **{k: [p["date"], p["arrival"]] for k, p in peaks.items()}})

    # strength words from the data, per group, as for doves
    scale = {}
    for key in DUCK_GROUPS:
        v = sorted(e[key][1] for e in index if e[key][1] > 0.05)
        q = (lambda p: round(v[int(len(v) * p)], 2)) if v else (lambda p: 0)
        scale[key] = {"few": q(0.25), "decent": q(0.55), "big": q(0.82)}
    json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "untested": True, "scale": scale, "sites": index},
              open(f"{OUT}/index.json", "w"), separators=(",", ":"))

    # map: freeze line per column and snow-covered nodes, by day
    if flow_fit is not None:
        fl = []
        for d in days:
            line = F.freeze_line(mall_ready.get(d, {}))
            snow = [flow_fit(*pt) for pt, f in F.feat.items()
                    if (f.get(d, {}).get("snow_cm") or 0) >= 2.54]
            fl.append({"date": d, "line": [flow_fit(la, lo) for lo, la in line.items()],
                       "snow": snow})
        json.dump({"days": fl}, open(f"{OUT}/flow.json", "w"), separators=(",", ":"))

    print(f"  ducks: {len(index)} published, {len(log_rows)} logged, "
          f"replay from {res['duck_mallard']['start']}, {time.time() - t0:.0f}s")
    return log_rows, nxt
