"""Pipeline runner shared by the CLI and the scheduled job."""
from datetime import datetime, timedelta, date
from statistics import mean

from .geo import arc_points, HOME, HOME_NAME
from .weather import OpenMeteo, ensemble_members
from .push import daily_features, score_day, Reservoir
from .front import (arc_passage, arc_passage_from, arc_passages_from,
                    front_speed_mph, cluster_fronts,
                    frontal_passages, arrival_forecast_wind, ensemble_confidence)
from .local import conditions, _summarise

ENGINE_VERSION = "0.1.0"


WIND_HORIZON = 16      # Open-Meteo max. The flight sim needs runway beyond
                       # the 10 days we display, or birds still in the air get
                       # written off as "not coming".

SEASON_START = (8, 15)   # matches the backtest window
DISPLAY_DAYS = 20        # how much band history the dashboard actually shows


def season_past_days(today=None):
    """Days of history needed to replay the season's depletion.

    The reservoir is the whole point: a finite northern population that
    drains as fronts push birds out and never refills. Starting it fresh in
    a 19-day window - which is what we were doing - measures 'was there a
    front this week', not 'how much of the fall has already happened'. In
    November it would report the north as untouched.
    """
    today = today or datetime.now().date()
    start = date(today.year, *SEASON_START)
    if today < start:                       # pre-season: nothing has drained
        return 5
    return max(5, min(92, (today - start).days))


def run(home=HOME, home_name=HOME_NAME, past=None, future=14, grid=None,
        local_hourly=None, ensemble=False):
    """Forecast for one hunter's location.

    `home` is the only thing that makes this location-specific; everything
    downstream takes it as a parameter. `grid`, when supplied, is a
    pre-fetched shared weather cache (see dove/grid.py) so a build covering
    hundreds of locations pays for the weather once rather than per location.
    """
    past = season_past_days() if past is None else past
    arcs, events, arc_series = arc_points(home), [], {}
    for idx, arc in arcs.items():
        if grid is not None:
            pp = [grid.features(*p) for p in arc["points"]]
            band_passages = [grid.passages(*p) for p in arc["points"]]
        else:
            series = OpenMeteo().hourly(arc["points"], past_days=past, forecast_days=WIND_HORIZON)
            hourly = [s["hourly"] for s in series]
            pp = [daily_features(h) for h in hourly]
            band_passages = None
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
        # Drained across the full season above; published for the display
        # window only, so a correct reservoir does not bloat the payload.
        arc_series[idx] = {d: daily[d] for d in sorted(daily)[-DISPLAY_DAYS:]}

        # ALL quorum-passing passages at this band, not just the strongest -
        # otherwise a band drops out of a front's chain whenever its biggest
        # event belongs to a different system, and the front appears to skip
        # a latitude, which a southward boundary cannot do.
        pp_in = band_passages if band_passages is not None else [frontal_passages(h) for h in hourly]
        for ev in arc_passages_from(pp_in):
            win = [(ev["when"].date() + timedelta(days=k)).isoformat() for k in (0, 1)]
            ev.update(arc=idx, dist_mi=arc["dist_mi"], north_mi=arc["north_mi"],
                      mean_lat=arc["mean_lat"], label=arc["label"],
                      index=max(daily.get(w, {}).get("index", 0.0) for w in win))
            events.append(ev)

    if grid is not None and local_hourly is None:
        # home is a lattice node, so its own features and passages are
        # already cached. Display-only extras (gusts, rain, sunrise) are
        # fetched client-side for the hunter's exact coordinates.
        hf, hp = grid.features(*home), grid.passages(*home)
        local_days = []
        local_fronts = [{"when": t.isoformat(timespec="minutes"), "strength": s}
                        for t, s in (hp or [])]
        home_push = {d: v["wind_push"] for d, v in (hf or {}).items()}
    else:
        local_days, local_fronts, home_push = _local_safe(home, local_hourly)

    # Southward wind push by day and latitude: the four bands plus the
    # fields. This is the wind field the birds actually fly through.
    push_field = {}
    for idx, arc in arcs.items():
        for d, v in arc_series[idx].items():
            push_field.setdefault(d, {})[arc["mean_lat"]] = v.get("obs", {}).get("push_mph", 0.0)
    for d, v in home_push.items():
        push_field.setdefault(d, {})[home[0]] = v

    fronts = []
    for n, fr in enumerate(cluster_fronts(events), 1):
        spd = front_speed_mph(fr)
        eta = None
        if spd:
            hrs = (fr[-1]["mean_lat"] - home[0]) * 69.0 / spd
            eta = (fr[-1]["when"] + timedelta(hours=hrs)).isoformat(timespec="minutes")
        chain = [e["arc"] for e in fr]
        # A southward boundary cannot cross band 4 then band 2 without
        # crossing band 3. If it looks like it did, that band's passage was
        # missed - say so rather than present a physically impossible chain.
        skipped = [b for a, c in zip(chain, chain[1:]) for b in range(c + 1, a)]
        fronts.append({
            "id": n, "arcs": chain, "skipped_bands": skipped,
            "speed_mph": spd, "reaches_home": eta,
            "passages": [{"arc": e["arc"], "when": e["when"].isoformat(timespec="minutes"),
                          "strength": e["strength"], "points_firing": e["points_firing"],
                          "index": e["index"]} for e in fr],
        })

    if ensemble is False:                      # single-location path: fetch it
        try:
            _members = ensemble_members(home)  # one call, reused by every front
        except Exception as ex:
            print(f"  ensemble skipped ({type(ex).__name__})")
            _members = None
    else:
        _members = ensemble                    # fan-out supplies it (or None)

    _arr = arrival_forecast_wind(events, push_field, home[0], days_out=future)

    # Replace the extrapolated ETA with the DETECTED arrival at the fields.
    # Match each tracked boundary to the strongest local passage that happens
    # after its last band crossing. Keep the extrapolation alongside so the
    # deceleration is visible rather than hidden.
    for f in fronts:
        last = max(p["when"] for p in f["passages"])
        cand = [p for p in local_fronts if p["when"] > last]
        f["eta_extrapolated"] = f.pop("reaches_home")
        if cand:
            best = max(cand, key=lambda p: p["strength"])
            f["reaches_home"] = best["when"]
            f["reaches_home_source"] = "detected"
            hrs = (datetime.fromisoformat(best["when"])
                   - datetime.fromisoformat(last)).total_seconds() / 3600.0
            north = max(a["north_mi"] for i, a in arcs.items() if i == min(f["arcs"]))
            f["actual_speed_mph"] = round(north / hrs, 1) if hrs > 0 else None
            f["confidence"] = (ensemble_confidence(_members, datetime.fromisoformat(best["when"]))
                               if _members else None)
        else:
            f["reaches_home"] = None
            f["reaches_home_source"] = "none detected"
            f["actual_speed_mph"] = None

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "home": {"name": home_name, "lat": home[0], "lon": home[1]},
        "engine_version": ENGINE_VERSION,
        "arcs": {str(i): {k: a[k] for k in ("dist_mi", "north_mi", "label", "mean_lat", "half_width_mi", "width_mi", "usable")}
                 for i, a in arcs.items()},
        "arc_scores": {str(i): v for i, v in arc_series.items()},
        "fronts": fronts,
        "arrival": _arr["days"],
        "still_airborne": _arr["still_airborne"],
        # Conditions at the fields themselves. Never fatal — the arrival
        # forecast is the product; this is the useful extra beside it.
        "local": local_days,
        "local_fronts": local_fronts,
    }


def _local_safe(home=HOME, hourly=None):
    """Returns (per-day conditions, detected local frontal passages).

    The front's arrival at the fields is DETECTED in the local hourly series,
    not extrapolated from how fast it crossed Nebraska. Fronts decelerate
    pushing into Texas heat in September, and a linear fit from the northern
    bands ran 2.5 days early on the first front we checked.
    """
    try:
        if hourly is None:
            days, hourly = conditions(home, want_hourly=True)
        else:
            days = _summarise(hourly)          # hourly is a whole API response here
            hourly = hourly["hourly"]
        passes = [{"when": dtm.isoformat(timespec="minutes"), "strength": sc}
                  for dtm, sc in frontal_passages(hourly)]
        push = {d: f["wind_push"] for d, f in daily_features(hourly).items()}
        return days, passes, push
    except Exception as e:
        print(f"  local conditions skipped ({type(e).__name__})")
        return [], [], {}
