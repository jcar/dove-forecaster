"""eBird API 2.0 client — live ground truth.  See DECISIONS.md D9.

Three species, deliberately:
    moudov  Mourning Dove           migratory — the target
    whwdov  White-winged Dove       partially migratory, expanding north into DFW
    eucdov  Eurasian Collared-Dove  non-native, NON-MIGRATORY — the CONTROL

The control is the point. If the Push Index correlates with mourning dove
density but NOT with collared-dove density, we are detecting migration.
If both spike on the same days, we are detecting BIRDERS (the observer-effort
confound) and the model is measuring the wrong thing entirely.
"""
import json
import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SPECIES = {"moudov": "Mourning Dove",
           "whwdov": "White-winged Dove",
           "eucdov": "Eurasian Collared-Dove"}
MIGRATORY = ("moudov", "whwdov")
CONTROL = "eucdov"

BASE = "https://api.ebird.org/v2"
CACHE = "data/ebird"


def _key():
    k = os.environ.get("EBIRD_API_KEY")
    if not k and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("EBIRD_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        raise RuntimeError("EBIRD_API_KEY not set (env or .env)")
    return k


_SESSION = None


def _session():
    """Pooled connections + backoff. A season backfill is thousands of
    requests; without retries one transient TLS timeout kills the run, and
    the daily job runs unattended in CI where nobody sees it fail."""
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({"X-eBirdApiToken": _key()})
        retry = Retry(total=5, backoff_factor=1.5,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET"]))
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        _SESSION = s
    return _SESSION


def _get(path, **params):
    last = None
    for attempt in range(4):
        try:
            r = _session().get(f"{BASE}/{path}", params=params, timeout=(10, 45))
            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(2.0 * (attempt + 1))   # Retry() does not cover read timeouts
    raise last


def daily_index(region, d, pause=0.12):
    """Effort-normalized dove density for one region on one date.

    Denominator is COMPLETE checklists with a real duration — never raw
    observation counts, which measure how many people went birding.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{region}_{d.isoformat()}.json"
    if os.path.exists(path):
        return json.load(open(path))

    lists = _get(f"product/lists/{region}/{d.year}/{d.month}/{d.day}", maxResults=200)
    agg = {s: {"birds": 0, "lists_detected": 0, "x_only": 0} for s in SPECIES}
    n_complete, hours = 0, 0.0

    for L in lists:
        c = _get(f"product/checklist/view/{L['subId']}")
        time.sleep(pause)
        dur = c.get("durationHrs")
        # complete lists with real effort only; incidental sightings carry no denominator
        if not c.get("allObsReported") or not dur or dur <= 0:
            continue
        n_complete += 1
        hours += dur
        for o in c.get("obs", []):
            s = o.get("speciesCode")
            if s not in SPECIES:
                continue
            agg[s]["lists_detected"] += 1
            n = o.get("howManyAtleast")
            if n is None:
                agg[s]["x_only"] += 1      # reported as "X" = present, uncounted
            else:
                agg[s]["birds"] += int(n)

    out = {"region": region, "date": d.isoformat(),
           "n_checklists_total": len(lists), "n_complete": n_complete,
           "checklist_hours": round(hours, 2), "species": {}}
    for s in SPECIES:
        a = agg[s]
        out["species"][s] = {
            "birds": a["birds"], "lists_detected": a["lists_detected"],
            "x_only": a["x_only"],
            "per_checklist": round(a["birds"] / n_complete, 3) if n_complete else None,
            "per_hour": round(a["birds"] / hours, 3) if hours else None,
            "frequency": round(a["lists_detected"] / n_complete, 3) if n_complete else None,
        }
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out
