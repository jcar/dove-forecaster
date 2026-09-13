"""WeatherProvider interface + Open-Meteo adapters.  See DECISIONS.md D8.

Two adapters behind one interface so the live source (NWS, public domain)
and the backtest source (ERA5 archive) can differ without the engine caring.
"""
import requests

HOURLY = ["temperature_2m", "wind_speed_10m", "wind_direction_10m",
          "surface_pressure", "cloud_cover"]

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# Pinned, not left to a default blend. ECMWF IFS is the strongest global
# model for FRONTAL TIMING in the 3-10 day window, which is the only thing
# this forecast depends on. An unpinned "best match" can silently change
# which model is behind a number, and then a forecast shift means nothing.
MODEL = "ecmwf_ifs025"
ENSEMBLE_MODEL = "gfs025"          # 31 members, for the uncertainty range


class WeatherProvider:
    def hourly(self, points, **kw):
        raise NotImplementedError


class OpenMeteo(WeatherProvider):
    """mode='archive' -> ERA5 reanalysis (deep history, ~5 day lag).
       mode='forecast' -> forecast endpoint, supports past_days for recent obs.
    """

    def __init__(self, mode="forecast", timeout=90, model=MODEL):
        self.mode, self.timeout, self.model = mode, timeout, model

    def hourly(self, points, start=None, end=None, past_days=None, forecast_days=None,
               hourly=None, daily=None):
        params = {
            "latitude": ",".join(str(p[0]) for p in points),
            "longitude": ",".join(str(p[1]) for p in points),
            "hourly": ",".join(hourly or HOURLY),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "America/Chicago",
        }
        if daily:
            params["daily"] = ",".join(daily)
        if self.model and self.mode != "archive":
            params["models"] = self.model
        if self.mode == "archive":
            url, params["start_date"], params["end_date"] = ARCHIVE_URL, start, end
        else:
            url = FORECAST_URL
            if past_days:
                params["past_days"] = past_days
            if forecast_days:
                params["forecast_days"] = forecast_days
        r = requests.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else [data]


def ensemble_members(point, hourly=None, forecast_days=10, timeout=120):
    """Every member of the ensemble as its own hourly series.

    One deterministic run gives a single answer with no honesty about how
    sure it is. Running the frontal detector across all members turns
    'the front arrives Friday 7pm' into a range, which is what we can
    actually defend.
    """
    hourly = hourly or HOURLY
    r = requests.get(ENSEMBLE_URL, params={
        "latitude": point[0], "longitude": point[1],
        "hourly": ",".join(hourly), "models": ENSEMBLE_MODEL,
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "America/Chicago", "forecast_days": forecast_days,
    }, timeout=timeout)
    r.raise_for_status()
    h = r.json()["hourly"]

    suffixes = sorted({k.split("_member")[1] for k in h if "_member" in k})
    out = [{"time": h["time"], **{v: h[v] for v in hourly if v in h}}]   # control
    for s in suffixes:
        m = {"time": h["time"]}
        ok = True
        for v in hourly:
            key = f"{v}_member{s}"
            if key not in h:
                ok = False
                break
            m[v] = h[key]
        if ok:
            out.append(m)
    return out
