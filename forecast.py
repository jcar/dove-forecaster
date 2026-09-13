#!/usr/bin/env python3
"""Human-readable view of the same pipeline the scheduled job runs."""
from datetime import datetime
from dove.engine import run

r = run()

print("\n  FRONTAL PASSAGES DETECTED UPSTREAM")
print("  " + "-" * 74)
if not r["fronts"]:
    print("  none — no organized boundary in the watch cone.")
for fr in r["fronts"]:
    for p in fr["passages"]:
        a = r["arcs"][str(p["arc"])]
        when = datetime.fromisoformat(p["when"])
        print(f"  Arc {p['arc']} ({a['dist_mi']:>3} mi) {a['label']:<26} "
              f"{when:%a %b %d %H:%M}  str {p['strength']:>5.1f}  "
              f"{p['points_firing']}/5 pts  push idx {p['index']:.0f}")
print("  " + "-" * 74)
for fr in r["fronts"]:
    eta = f"  -> reaches the fields {datetime.fromisoformat(fr['reaches_home']):%a %b %d %H:%M}" if fr["reaches_home"] else ""
    print(f"  front {fr['id']}: {'+'.join('arc'+str(a) for a in fr['arcs']):<22} "
          f"speed {str(fr['speed_mph'])+' mph' if fr['speed_mph'] else 'unresolved':<12}{eta}")

print(f"\n  ARRIVAL FORECAST — {r['home']['name']}")
print("  " + "-" * 74)
for row in r["arrival"]:
    src = "  <- " + ", ".join(f"arc{a}:{v}" for a, v in row["from_arcs"]) if row["from_arcs"] else ""
    print(f"  {row['date']}  {row['arrival']:>6.1f}  {'#' * int(row['arrival'] / 2):<26}{src}")
print("  " + "-" * 74 + "\n")
