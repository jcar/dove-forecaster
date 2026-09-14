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
import json
import math
import os
from datetime import date, datetime

from .weather import OpenMeteo
from .push import daily_features
from .front import frontal_passages

LAT_STEP = 0.75
LON_STEP = 1.00      # ~57 mi. Coarsened from 0.50 to fit Open-Meteo's free
                     # quota, which bills by LOCATION-DAYS, not by request -
                     # batching 200 coords into one call saves round-trips and
                     # nothing else. Latitude spacing is untouched because
                     # front_speed_mph fits against latitude; longitude only
                     # samples across the corridor, and 1 deg still gives ~8
                     # independent stations per 420-mile band.
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

    def __init__(self, past_days, forecast_days=16, model=None, cache_dir=None):
        self.past_days, self.forecast_days = past_days, forecast_days
        self.model = model
        self._feat, self._pass = {}, {}
        self.requests = 0
        self.points = 0
        self.cache_dir = cache_dir
        self.from_disk = 0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # Past weather never changes, so it is fetched once and kept forever.
    # Without this the daily cost grows all season - 40k location-days today,
    # 95k by mid-November - because every run re-downloads the whole season.
    def _path(self, pt):
        return os.path.join(self.cache_dir, f"{pt[0]}_{pt[1]}.json")

    def _load_disk(self, pt):
        p = self._path(pt)
        if not os.path.exists(p):
            return {}, []
        d = json.load(open(p))
        return d.get("features", {}), [(datetime.fromisoformat(t), s) for t, s in d.get("passages", [])]

    def _save_disk(self, pt, feat, passes):
        today = date.today().isoformat()
        past_feat = {k: v for k, v in feat.items() if k < today}
        past_pass = [(t.isoformat(), s) for t, s in passes if t.date().isoformat() < today]
        json.dump({"features": past_feat, "passages": past_pass},
                  open(self._path(pt), "w"), separators=(",", ":"))

    def load(self, points, progress=None):
        """Fetch in batches, reduce each point, discard the raw series.

        Holding every raw hourly series at once is ~700 MB of boxed floats
        on a CI runner. Streaming keeps peak memory flat.
        """
        todo = sorted({snap(*p) for p in points} - set(self._feat))
        api = OpenMeteo() if self.model is None else OpenMeteo(model=self.model)
        self.failed = 0
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            try:
                series = api.hourly(chunk, past_days=self.past_days,
                                    forecast_days=self.forecast_days)
            except Exception as ex:
                # Partial data beats no data for a daily job. Nodes that fail
                # keep yesterday's cached history and are simply absent from
                # today's field; the next run picks them up.
                self.failed += len(chunk)
                print(f"    batch failed ({type(ex).__name__}), skipping "
                      f"{len(chunk)} nodes", flush=True)
                continue
            self.requests += 1
            for pt, s in zip(chunk, series):
                h = s["hourly"]
                feat, passes = daily_features(h), frontal_passages(h)
                if self.cache_dir:
                    old_f, old_p = self._load_disk(pt)
                    if old_f:
                        self.from_disk += 1
                    merged_f = {**old_f, **feat}          # fresh data wins
                    seen = {t for t, _ in passes}
                    merged_p = sorted(passes + [x for x in old_p if x[0] not in seen],
                                      key=lambda x: x[0])
                    feat, passes = merged_f, merged_p
                    self._save_disk(pt, feat, passes)
                self._feat[pt], self._pass[pt] = feat, passes
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
