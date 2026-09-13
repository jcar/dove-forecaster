"""WeatherProvider interface + Open-Meteo adapters.  See DECISIONS.md D8.

Two adapters behind one interface so the live source (NWS, public domain)
and the backtest source (ERA5 archive) can differ without the engine caring.
"""
import requests

HOURLY = ["temperature_2m", "wind_speed_10m", "wind_direction_10m",
          "surface_pressure", "cloud_cover"]

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherProvider:
    def hourly(self, points, **kw):
        raise NotImplementedError


class OpenMeteo(WeatherProvider):
    """mode='archive' -> ERA5 reanalysis (deep history, ~5 day lag).
       mode='forecast' -> forecast endpoint, supports past_days for recent obs.
    """

    def __init__(self, mode="forecast", timeout=90):
        self.mode, self.timeout = mode, timeout

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
