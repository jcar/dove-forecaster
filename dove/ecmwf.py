"""ECMWF IFS open data, read directly - the same model we already pin
(weather.MODEL = "ecmwf_ifs025"), without a per-point meter.

Open-Meteo bills by location-days, so cost grows with every grid point we
add. ECMWF publishes the whole globe as files, free (CC-BY-4.0), four runs a
day: 3-hourly to 144 h, 6-hourly to 360 h. We download only the seven fields
the model reads, by byte range from each file's index, then read any number
of points out of the grid for nothing. Cost no longer depends on coverage.

Output is shaped exactly like an Open-Meteo "hourly" block - same keys, same
units, local-time stamps - so daily_features and frontal_passages run on it
unchanged. Hourly values between model steps are linear in time (wind as
u/v components, then converted), which is also what Open-Meteo does with
this model. See DECISIONS D23.

Data: ECMWF open data, https://www.ecmwf.int - Contains modified ECMWF data.
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

MIRRORS = ["https://data.ecmwf.int/forecasts",
           "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"]
LONG_STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6))
SHORT_STEPS = [0, 3, 6, 9]          # past days: the shortest lead of each run
# (param, levelist) -> output key
FIELDS = [("2t", None), ("sp", None), ("tcc", None), ("10u", None), ("10v", None),
          ("u", "925"), ("v", "925")]
MS_TO_MPH = 2.2369362920544

_S = None


def _session():
    global _S
    if _S is None:
        _S = requests.Session()
        a = requests.adapters.HTTPAdapter(pool_maxsize=32, max_retries=requests.adapters.Retry(
            total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504)))
        _S.mount("https://", a)
    return _S


def _get(path, rng=None, timeout=60):
    """Try each mirror in turn; ECMWF's own server first, the AWS copy second."""
    last = None
    for base in MIRRORS:
        try:
            h = {"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {}
            r = _session().get(f"{base}/{path}", headers=h, timeout=timeout)
            if r.status_code == 404:
                last = FileNotFoundError(path)
                continue
            r.raise_for_status()
            return r
        except (requests.RequestException,) as ex:
            last = ex
    raise last


def _stem(run, step):
    return (f"{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/"
            f"{run:%Y%m%d%H}0000-{step}h-oper-fc")


def latest_run(now=None, need_step=360):
    """Newest 00z/12z run whose LAST step is already published."""
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=t.hour % 12)
    for _ in range(6):
        try:
            _get(_stem(t, need_step) + ".index", timeout=20)
            return t
        except Exception:
            t -= timedelta(hours=12)
    raise RuntimeError("no complete ECMWF open-data run in the last 3 days")


def _grid_index(points):
    """Flat indices into the 1440 x 721 global grid (lat 90 -> -90, lon from
    -180). Lattice nodes sit on multiples of 0.25 deg, so this is exact."""
    out = []
    for lat, lon in points:
        i = int(round((90.0 - lat) / 0.25))
        j = int(round(((lon + 180.0) % 360.0) / 0.25)) % 1440
        out.append(i * 1440 + j)
    return out


def _read_step(run, step, idx):
    """{(param, level): [value per point]} for one model step."""
    import eccodes
    stem = _stem(run, step)
    rows = [json.loads(l) for l in _get(stem + ".index").text.splitlines() if l.strip()]
    out = {}
    for param, lev in FIELDS:
        hit = [r for r in rows if r["param"] == param and r.get("levelist") == lev]
        if not hit:
            raise KeyError(f"{param}/{lev} missing at {stem}")
        r = hit[0]
        msg = _get(stem + ".grib2", (r["_offset"], r["_offset"] + r["_length"] - 1)).content
        h = eccodes.codes_new_from_message(msg)
        try:
            vals = eccodes.codes_get_values(h)
        finally:
            eccodes.codes_release(h)
        out[(param, lev)] = [float(vals[k]) for k in idx]
    return out


def _download(jobs, idx, workers=12):
    """jobs: [(run, step)] -> {valid_time_utc: fields}. Later runs overwrite
    earlier ones at the same valid time (shorter lead wins)."""
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda js: (js, _read_step(js[0], js[1], idx)), jobs))
    by_time = {}
    for (run, step), fields in sorted(res, key=lambda x: x[0][0]):
        by_time[run + timedelta(hours=step)] = fields
    return by_time


def _interp(by_time, k):
    """Hourly linear interpolation of field k between model steps."""
    ts = sorted(by_time)
    t0, t1 = ts[0], ts[-1]
    out, a = {}, 0
    t = t0
    while t <= t1:
        while a + 1 < len(ts) and ts[a + 1] <= t:
            a += 1
        if ts[a] == t or a + 1 >= len(ts):
            out[t] = by_time[ts[a]][k]
        else:
            lo, hi = ts[a], ts[a + 1]
            f = (t - lo).total_seconds() / (hi - lo).total_seconds()
            va, vb = by_time[lo][k], by_time[hi][k]
            out[t] = [x + (y - x) * f for x, y in zip(va, vb)]
        t += timedelta(hours=1)
    return out


def _speed_dir(u, v):
    sp = math.hypot(u, v) * MS_TO_MPH
    d = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0     # direction FROM
    return round(sp, 1), round(d)


def hourly(points, past_days=2, run=None, tz=None, steps=None, progress=None):
    """Open-Meteo-shaped hourly series for every point, from one download.

    Past days come from the first 9 h of each earlier 00z/12z run - the
    shortest-lead, closest-to-observed slice - and the forecast from the
    newest complete run. Each point is stamped in its OWN local time zone
    (regions.tz_for) unless `tz` forces one for every point.
    """
    from .regions import tz_for
    run = run or latest_run()
    steps = steps or LONG_STEPS
    jobs = [(run, s) for s in steps]
    for k in range(1, past_days * 2 + 2):
        jobs += [(run - timedelta(hours=12 * k), s) for s in SHORT_STEPS]
    idx = _grid_index(points)
    t0 = time.time()
    by_time = _download(jobs, idx)
    if progress:
        progress(len(jobs), time.time() - t0)

    series = {k: _interp(by_time, k) for k in FIELDS}
    times = sorted(series[FIELDS[0]])
    zones = {}
    out = []
    for p in range(len(points)):
        name = tz or tz_for(*points[p])
        zone = zones.setdefault(name, ZoneInfo(name))
        h = {"time": [], "temperature_2m": [], "surface_pressure": [], "cloud_cover": [],
             "wind_speed_10m": [], "wind_direction_10m": [],
             "wind_speed_925hPa": [], "wind_direction_925hPa": []}
        for t in times:
            g = lambda k: series[k][t][p]
            h["time"].append(t.astimezone(zone).strftime("%Y-%m-%dT%H:%M"))
            h["temperature_2m"].append(round((g(("2t", None)) - 273.15) * 9 / 5 + 32, 1))
            h["surface_pressure"].append(round(g(("sp", None)) / 100.0, 1))
            h["cloud_cover"].append(round(max(0.0, min(1.0, g(("tcc", None)))) * 100))
            s10, d10 = _speed_dir(g(("10u", None)), g(("10v", None)))
            s9, d9 = _speed_dir(g(("u", "925")), g(("v", "925")))
            h["wind_speed_10m"].append(s10); h["wind_direction_10m"].append(d10)
            h["wind_speed_925hPa"].append(s9); h["wind_direction_925hPa"].append(d9)
        out.append({"latitude": points[p][0], "longitude": points[p][1], "hourly": h})
    return out
