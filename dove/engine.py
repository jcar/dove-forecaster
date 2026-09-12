"""Pipeline runner shared by the CLI and the scheduled job."""
from datetime import datetime, timedelta
from statistics import mean

from .geo import arc_points, HOME
from .weather import OpenMeteo
from .push import daily_features, score_day, Reservoir
from .front import arc_passage, front_speed_mph, arrival_forecast, cluster_fronts

ENGINE_VERSION = "0.1.0"


def run(past=5, future=10):
    arcs, events, arc_series = arc_points(), [], {}
    for idx, arc in arcs.items():
        series = OpenMeteo().hourly(arc["points"], past_days=past, forecast_days=future)
        hourly = [s["hourly"] for s in series]
        pp = [daily_features(h) for h in hourly]
        dates = sorted(set.intersection(*[set(p) for p in pp]))
        res, daily = Reservoir(), {}
        for i, d in enumerate(dates):
            if i == 0:
                continue
            ss = [score_day(p[d], p[dates[i - 1]], arc["mean_lat"], d, res.level) for p in pp]
            daily[d] = {
                "index": round(mean(s["index"] for s in ss), 1),
                "raw": round(mean(s["raw"] for s in ss), 1),
                "gate": round(ss[0]["gate"], 3),
                "reservoir": round(res.level, 3),
                "components": {k: round(mean(s["components"][k] for s in ss), 1)
                               for k in ss[0]["components"]},
                "obs": {k: round(mean(s["obs"][k] for s in ss), 1) for k in ss[0]["obs"]},
            }
            res.debit(daily[d]["raw"] * daily[d]["gate"])
        arc_series[idx] = daily

        ev = arc_passage(hourly)
        if ev:
            win = [(ev["when"].date() + timedelta(days=k)).isoformat() for k in (0, 1)]
            ev.update(arc=idx, dist_mi=arc["dist_mi"], mean_lat=arc["mean_lat"], label=arc["label"],
                      index=max(daily.get(w, {}).get("index", 0.0) for w in win))
            events.append(ev)

    fronts = []
    for n, fr in enumerate(cluster_fronts(events), 1):
        spd = front_speed_mph(fr)
        eta = None
        if spd:
            hrs = (fr[-1]["mean_lat"] - HOME[0]) * 69.0 / spd
            eta = (fr[-1]["when"] + timedelta(hours=hrs)).isoformat(timespec="minutes")
        fronts.append({
            "id": n, "arcs": [e["arc"] for e in fr], "speed_mph": spd, "reaches_home": eta,
            "passages": [{"arc": e["arc"], "when": e["when"].isoformat(timespec="minutes"),
                          "strength": e["strength"], "points_firing": e["points_firing"],
                          "index": e["index"]} for e in fr],
        })

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine_version": ENGINE_VERSION,
        "arcs": {str(i): {k: a[k] for k in ("dist_mi", "label", "mean_lat", "half_angle")}
                 for i, a in arcs.items()},
        "arc_scores": {str(i): v for i, v in arc_series.items()},
        "fronts": fronts,
        "arrival": arrival_forecast(events),
    }
