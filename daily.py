#!/usr/bin/env python3
"""Scheduled run. Writes one immutable forecast per day.

The point of this file is the AUDIT TRAIL, not the forecast. Each run is
committed with a timestamp, so what the model claimed on a given morning is
provable after the fact and cannot be quietly retuned into looking right.
"""
import json
import os
from datetime import date
from dove.engine import run

OUT = "data/forecasts"


def main():
    os.makedirs(OUT, exist_ok=True)
    result = run()
    path = f"{OUT}/{date.today().isoformat()}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)

    peak = max(result["arrival"], key=lambda r: r["arrival"])
    print(f"wrote {path}")
    print(f"  fronts tracked: {len(result['fronts'])}")
    for fr in result["fronts"]:
        print(f"    front {fr['id']}: arcs {fr['arcs']} speed={fr['speed_mph']} eta={fr['reaches_home']}")
    print(f"  peak arrival {peak['arrival']} on {peak['date']}")


main()
