#!/usr/bin/env python3
"""Backfill effort-normalized dove density. Cached per day; safe to re-run."""
import sys
from datetime import date, timedelta
from dove.ebird import daily_index

REGION = sys.argv[1] if len(sys.argv) > 1 else "US-TX-113"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 30

end = date.today()
for k in range(DAYS, -1, -1):
    d = end - timedelta(days=k)
    try:
        r = daily_index(REGION, d)
        m = r["species"]["moudov"]
        print(f"{d}  {r['n_complete']:>3} lists {r['checklist_hours']:>6.1f}h  "
              f"moudov {str(m['per_hour']):>7}/hr", flush=True)
    except Exception as e:
        print(f"{d}  FAILED {type(e).__name__}: {e}", flush=True)
