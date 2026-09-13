"""One shared weather lattice for every location in the flyway.

Naively, 350 locations x 4 bands x 9 points = 12,600 weather points a day.
But locations only 50 miles apart look at almost exactly the same country
upstream, so the same point is fetched again and again.

Two ideas collapse that cost:

1. SNAP EVERYTHING TO ONE LATTICE. Band offsets are whole multiples of the
   lattice row spacing (2.25 = 3 rows of 0.75), so a band latitude is always
   a lattice row exactly. No interpolation, and no jitter injected into
   front_speed_mph's least-squares fit of passage time against latitude.

2. CACHE THE DERIVED QUANTITIES, NOT THE RAW SERIES. frontal_passages costs
   ~22 ms per point; raw hourly for the whole lattice is hundreds of MB. So
   each point is fetched, reduced to its derivatives, and the series thrown
   away immediately.

The band score survives this untouched because it factorises exactly:
score_day gives index = raw * gate * reservoir, and within one band `gate`
(a function of that band's latitude and the date) and `reservoir` are
identical across all points. So mean(index) == mean(raw) * gate * reservoir
algebraically - the per-point cache can hold `raw` alone and the assembled
answer is bit-for-bit what per-location fetching would have produced.
"""
import math
from .weather import OpenMeteo
from .push import daily_features
from .front import frontal_passages

LAT_STEP = 0.75
LON_STEP = 0.50
BAND_OFFSETS_DEG = (2.25, 4.50, 6.75, 9.00)     # = 155/310/466/621 mi
BATCH = 200                                      # Open-Meteo takes 200 coords/request


def snap_lat(lat):
    return round(round(lat / LAT_STEP) * LAT_STEP, 4)


def snap_lon(lon):
    return round(round(lon / LON_STEP) * LON_STEP, 4)


def snap(lat, lon):
    return (snap_lat(lat), snap_lon(lon))


class PointCache:
    """Per-lattice-point derivatives, fetched once and reused by every
    location whose bands touch that point."""

    def __init__(self, past_days, forecast_days=16, model=None):
        self.past_days, self.forecast_days = past_days, forecast_days
        self.model = model
        self._feat, self._pass = {}, {}
        self.requests = 0
        self.points = 0

    def load(self, points, progress=None):
        """Fetch in batches, reduce each point, discard the raw series.

        Holding every raw hourly series at once is ~700 MB of boxed floats
        on a CI runner. Streaming keeps peak memory flat.
        """
        todo = sorted({snap(*p) for p in points} - set(self._feat))
        api = OpenMeteo() if self.model is None else OpenMeteo(model=self.model)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            series = api.hourly(chunk, past_days=self.past_days,
                                forecast_days=self.forecast_days)
            self.requests += 1
            for pt, s in zip(chunk, series):
                h = s["hourly"]
                self._feat[pt] = daily_features(h)
                self._pass[pt] = frontal_passages(h)
                self.points += 1
                del h, s
            if progress:
                progress(min(i + BATCH, len(todo)), len(todo), self.requests)
        return self

    def features(self, lat, lon):
        return self._feat.get(snap(lat, lon))

    def passages(self, lat, lon):
        return self._pass.get(snap(lat, lon))

    def covers(self, points):
        return all(snap(*p) in self._feat for p in points)
