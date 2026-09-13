#!/usr/bin/env python3
"""Historical ground-truth backfill. Cached per day, resumable, safe to re-run."""
import sys, time
from datetime import date, timedelta
from dove.ebird import daily_index
import dove.ebird as E

REGION = "US-TX-113"
YEARS = [int(y) for y in sys.argv[1:]] or [2023, 2024, 2025]
t0 = time.time()
done = fail = 0
for y in YEARS:
    d, end = date(y, 8, 15), date(y, 11, 15)
    while d <= end:
        try:
            r = daily_index(REGION, d)
            done += 1
            if done % 10 == 0:
                print(f"{d}  {done} days  pace={E._PAUSE:.2f}s  "
                      f"elapsed={(time.time()-t0)/60:.0f}m", flush=True)
        except Exception as e:
            fail += 1
            print(f"{d}  FAILED {type(e).__name__}", flush=True)
        d += timedelta(days=1)
    print(f"--- {y} complete ({done} ok, {fail} failed) ---", flush=True)
print(f"DONE {done} days, {fail} failures, {(time.time()-t0)/60:.0f} min", flush=True)
