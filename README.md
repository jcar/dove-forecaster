# Dove Migration Forecaster

Predicts **when** migratory mourning doves arrive at fields you already hunt,
3–10 days out, by tracking weather triggers upstream.

Not a field-finder. It assumes you know your spots and answers the only
question you can't answer yourself: *what morning do I need to be standing
in one?*

## How it works

Four concentric **arcs** north of the hunter (150 / 300 / 450 / 600 mi),
in a cone that widens with distance — Texas is a wintering funnel, so the
contributing breeding range fans out as you look north.

Each arc is scored daily with a **Push Index**:

    raw   = wind(35) + tempdrop(25) + pressure(20) + clearing(10) + sharp(10)
    index = raw × photoperiod_gate × reservoir

- `photoperiod_gate` — northern arcs open earlier in the calendar.
- `reservoir` — each arc holds a finite population that depletes and never
  refills, so the first hard front of the fall outweighs the fourth.

**Frontal passages** are detected on the hourly series (wind veering
southward + pressure trough + falling temperature), require a 3-of-5 point
quorum per arc, and are clustered into distinct boundaries. The front's
southward speed is then *measured* by least-squares fit of passage time
against latitude — never assumed.

**Arrival** superposes one bird pulse per arc. Birds don't ride the front
in; they depart when it clears the latitude they're staged at, then fly
south at their own pace. The front outruns them, so the weather typically
shows up a day or two before the birds do.

## Run it

    pip install -r requirements.txt
    python forecast.py      # human-readable
    python daily.py         # writes data/forecasts/YYYY-MM-DD.json

A scheduled Action runs `daily.py` each morning and commits the result, so
every forecast is timestamped **before** the outcome is known. That audit
trail is the point — it's what makes the model gradeable instead of
retro-fittable.

## Status

Engine works. **Nothing is validated against actual birds yet.**
See `DECISIONS.md` for every decision, the biology behind it, and the six
scoring defects that only showed up once the thing was run.

## Privacy

Field coordinates are never committed. See `.gitignore`.
