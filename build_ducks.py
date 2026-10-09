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
from dove.profiles import DUCK_SPECIES, GROUP_OF
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


GROUP_NAMES = {"duck_mallard": "Mallards & big ducks", "duck_teal": "Teal",
               "duck_puddle": "Gadwall, wigeon & pintail"}


def _q(vals, p):
    v = sorted(x for x in vals if x > 1e-6)
    return v[min(len(v) - 1, int(len(v) * p))] if v else 0.0


def build(cache, sites, every, us_fit=None, flow_fit=None):
    """Species are modelled one by one (D30). Each is expressed in units of its
    OWN big push - the 82nd percentile of peak arrivals across published
    locations - so a pintail push and a mallard push weigh the same; groups are
    the sum of their species and "All ducks" the sum of the groups. The field
    only knows RELATIVE numbers, so this is the honest way to add them up."""
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

    # raw arrivals per species per location, then each species' own scale
    raw = {}
    for s in every:
        node = snap(s["lat"], s["lon"])
        raw[s["id"]] = {k: [res[k]["arrivals"].get(d, {}).get(node, 0.0) for d in days]
                        for k in DUCK_SPECIES}
    unit = {k: _q([max(raw[i][k][SHOW_PAST:]) for i in pub_ids], 0.82) or 1.0 for k in DUCK_SPECIES}

    def layers(sid):
        sp = {k: [v / unit[k] for v in raw[sid][k]] for k in DUCK_SPECIES}
        gr = {g: [sum(sp[k][i] for k in DUCK_SPECIES if GROUP_OF[k] == g) for i in range(len(days))]
              for g in GROUP_NAMES}
        al = [sum(gr[g][i] for g in GROUP_NAMES) for i in range(len(days))]
        return sp, gr, al

    mall_ready = res["mallar3"]["ready"]
    log_rows, index = {}, []
    r2 = lambda xs: [round(x, 2) for x in xs]
    for s in every:
        sid, node = s["id"], snap(s["lat"], s["lon"])
        sp, gr, al = layers(sid)
        row = {"lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"], "published": sid in pub_ids,
               "duck_all": r2(al[SHOW_PAST:])}
        row.update({g: r2(v[SHOW_PAST:]) for g, v in gr.items()})
        row.update({f"duck_{k}": r2(v[SHOW_PAST:]) for k, v in sp.items()})
        log_rows[sid] = row
        if sid not in pub_ids:
            continue
        sev, feats = F.sev.get(node, {}), F.feat.get(node, {})
        line = []                    # southernmost mallard-ready latitude in this column
        for d in days:
            rd = mall_ready.get(d, {})
            col = [pt[0] for pt, v in rd.items() if abs(pt[1] - node[1]) < 0.01 and v >= 0.5]
            line.append(min(col) if col else None)
        payload = {
            "id": sid, "lat": s["lat"], "lon": s["lon"], "flyway": s["flyway"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "untested": True, "dates": days, "today_index": SHOW_PAST,
            "all": r2(al),
            "groups": {g: {"name": GROUP_NAMES[g], "arrival": r2(v),
                           "species": [k for k in DUCK_SPECIES if GROUP_OF[k] == g]}
                       for g, v in gr.items()},
            "species": {k: {"name": DUCK_SPECIES[k].name, "group": GROUP_OF[k], "arrival": r2(v),
                            "trigger": DUCK_SPECIES[k].measure}
                        for k, v in sp.items()},
            "freeze": {"wsi": [sev.get(d, {}).get("wsi") for d in days],
                       "tmean_c": [feats.get(d, {}).get("tmean_c") for d in days],
                       "snow_cm": [feats.get(d, {}).get("snow_cm") for d in days],
                       "line_lat": line},
            "fronts": [t.isoformat(timespec="minutes") for t, _ in (cache._pass.get(node) or [])
                       if t.date().isoformat() >= days[0]],
        }
        json.dump(payload, open(f"{OUT}/loc/{sid}.json", "w"), separators=(",", ":"))

        def peak(xs):
            i = max(range(SHOW_PAST, len(days)), key=lambda j: xs[j])
            return [days[i], round(xs[i], 2)]
        index.append({"id": sid, "lat": s["lat"], "lon": s["lon"], "all": peak(al),
                      **{g: peak(v) for g, v in gr.items()},
                      **{k: peak(v) for k, v in sp.items()}})

    # strength words per layer, from the data (as for doves)
    keys = ["all"] + list(GROUP_NAMES) + list(DUCK_SPECIES)
    scale = {k: {"few": round(_q([e[k][1] for e in index], 0.25), 3),
                 "decent": round(_q([e[k][1] for e in index], 0.55), 3),
                 "big": round(_q([e[k][1] for e in index], 0.82), 3)} for k in keys}
    json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "untested": True, "scale": scale,
               "groups": {g: {"name": n, "species": [k for k in DUCK_SPECIES if GROUP_OF[k] == g]}
                          for g, n in GROUP_NAMES.items()},
               "species_names": {k: g.name for k, g in DUCK_SPECIES.items()},
               "sites": index},
              open(f"{OUT}/index.json", "w"), separators=(",", ":"))

    if flow_fit is not None:
        fl = []
        for d in days:
            line = F.freeze_line(mall_ready.get(d, {}))
            snow = [flow_fit(*pt) for pt, f in F.feat.items()
                    if (f.get(d, {}).get("snow_cm") or 0) >= 2.54]
            fl.append({"date": d, "line": [flow_fit(la, lo) for lo, la in line.items()], "snow": snow})
        fsites = []
        for s in sites:
            sp, gr, al = layers(s["id"])
            fsites.append({"id": s["id"], "xy": list(flow_fit(s["lat"], s["lon"])),
                           "a": {"all": r2(al), **{g: r2(v) for g, v in gr.items()}}})
        json.dump({"days": fl, "sites": fsites}, open(f"{OUT}/flow.json", "w"), separators=(",", ":"))

    print(f"  ducks: {len(index)} published, {len(log_rows)} logged, "
          f"replay from {res['mallar3']['start']}, {time.time() - t0:.0f}s")
    return log_rows, nxt
