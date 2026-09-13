#!/usr/bin/env python3
"""Scheduled run. Writes one immutable forecast per day.

The point of this file is the AUDIT TRAIL, not the forecast. Each run is
committed with a timestamp, so what the model claimed on a given morning is
provable after the fact and cannot be quietly retuned into looking right.
"""
import json
import os
from datetime import date, timedelta
from dove.engine import run
from dove.ebird import daily_index
from dove.wave import snapshot

OUT = "data/forecasts"


def main():
    os.makedirs(OUT, exist_ok=True)
    result = run()
    path = f"{OUT}/{date.today().isoformat()}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)

    # Ground truth for the days just past. Sustainable at ~30 calls/day;
    # the historical backfill is NOT (see DECISIONS F9). Never fatal — a
    # throttled eBird must not cost us the weather forecast.
    for back in (2, 1):
        d = date.today() - timedelta(days=back)
        try:
            g = daily_index("US-TX-113", d)
            print(f"  ebird {d}: {g['n_complete']} lists, "
                  f"moudov {g['species']['moudov']['per_hour']}/hr")
        except Exception as e:
            print(f"  ebird {d}: skipped ({type(e).__name__})")

    # Flyway-wide dove density. ~39 calls; accumulates the southward wave.
    # Counts are NOT comparable between bands - DFW has 50 reporting
    # locations against 4-8 in Nebraska. Each band is read against its own
    # history, never against another band.
    try:
        w = snapshot(date.today().isoformat())
        tot = sum(v["birds"] for sp in w["counts"].values()
                  for d in sp.get("moudov", {}).values() for v in [d])
        print(f"  wave: {len(w['counts'])} circles, {tot} mourning doves logged")
    except Exception as e:
        print(f"  wave skipped ({type(e).__name__})")

    peak = max(result["arrival"], key=lambda r: r["arrival"])
    print(f"wrote {path}")
    print(f"  fronts tracked: {len(result['fronts'])}")
    for fr in result["fronts"]:
        print(f"    front {fr['id']}: arcs {fr['arcs']} speed={fr['speed_mph']} eta={fr['reaches_home']}")
    print(f"  peak arrival {peak['arrival']} on {peak['date']}")


# Guarded: importing this module must never start fetching weather.
if __name__ == "__main__":
    main()