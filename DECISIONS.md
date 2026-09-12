# Dove Migration Forecaster — Locked Decisions

Last updated: 2026-09-12

## Product

**One job:** tell a hunter with known fields *when* migratory flight doves will
arrive, 3-10 days out.

Explicitly NOT building (shelved, not cancelled):
- Crop Harvest Heatmap / NDVI pipeline
- CDL connected-component field polygon derivation
Rationale: solves field *discovery*. Founder already knows his fields.

## D1 — Atomic unit: the field
Superseded in practice: with n=6 known fields, pins are entered by hand.
CDL polygon derivation (D2 below) is shelved with the heatmap.

## D2 — Field geometry: CDL connected components  [SHELVED]
CDL raster -> mask dove crops -> scipy.ndimage.label -> rasterio shapes
-> drop <5 acres -> erode 1px inward (kills road/treeline mixed pixels).
Keep on file. Free, no vendor, no ML.

## D3 — Forecast horizon: 3-10 day operational + 0-48hr confirmation
- Forecast voice: "Front clears Nebraska Wed night, birds Thu AM."
- Confirmation voice: "That front delivered. Go in the morning."
Confirmation is ~free: same trigger function run against observations
instead of forecasts. Also serves as the grading loop.

## D4 — Upstream watch region: concentric arcs, widening cone
Center: Dallas TX, ~32.78N -96.80W. Cone centered due north, widening with
distance (TX is a wintering funnel; source range fans out going north).

| Arc | Dist    | Region                                      | Lead   |
|-----|---------|---------------------------------------------|--------|
| 1   | ~150 mi | S Oklahoma / Red River (Ardmore, Ada)       | ~1 day |
| 2   | ~300 mi | Central+NE OK (OKC, Stillwater, Tulsa)      | 1-2 d  |
| 3   | ~450 mi | Kansas (Wichita, Salina, Emporia, Dodge)    | 2-4 d  |
| 4   | ~600 mi | Nebraska / NW Missouri (Lincoln, St. Joe)   | 4-6 d  |

Front velocity measured ACROSS arcs is what produces an arrival date.
Arc distances + cone width are strawmen; grading loop corrects them.

## D5 — Trigger: weighted Push Index (0-100), per arc, per day

    raw = wind(0-35) + tempdrop(0-25) + pressure(0-20)
        + clearing(0-10) + sharpness(0-10)

    PushIndex = raw * P_photoperiod * R_reservoir

- Wind term uses the real vector: speed * cos(theta), theta = met. direction
  (degrees FROM north). A 340 wind still delivers ~94% push.
- P_photoperiod (0-1): day length at THAT ARC's latitude. Zeroes out the
  January-front false positive.
- R_reservoir (0-1): each arc holds a finite population that depletes and
  does not refill. First front of fall >> fourth identical front.
  This is what lets the model say "this is the big one."

Chosen over hard thresholds (brittle AND-rules), synoptic frontal analysis
(redundant w/ arc geometry), and ML (no labels until season 1 generates them).
The continuous score IS the future regression target.

## D6 — Delivery: web dashboard
4 arcs x 10 day timeline + 6 field pins. Notifications deferred to v2
(web push, no rework). Dashboard chosen partly BECAUSE season 1 is
calibration - notifications would hide the model's misses.

## Biology notes that shaped the above
- Mourning doves are DIURNAL migrants. Rules out NEXRAD/BirdCast (tuned for
  nocturnal passerines, filter daytime returns as clutter). Promotes eBird
  to primary ground truth - doves move when birders are outside.
- Photoperiod sets the season; fronts set the day. We are not predicting
  whether birds come, only which morning the staged ones leave.
- Resident vs migrant are different populations under different laws.
  We forecast migrants only.
- Central Mgmt Unit axis runs roughly NNE->SSW; Dallas sits at the mouth
  of the funnel, so cone is wide and near due north. Needs banding-data
  verification.

## Cost posture
Every data layer has a free, authoritative, government source.
No paid data vendors in the MVP. Spend is compute only.

---

# Phase 2 — Tech Stack

## D8 — Weather: split by license fit
One `WeatherProvider` interface, two adapters.
- BACKTEST: Open-Meteo ERA5 archive (1940-present, free, non-commercial OK
  for research). Note ~5 day lag; for recent-season use the forecast
  endpoint with past_days instead.
- LIVE: NWS api.weather.gov (public domain, no key, commercial-safe forever).
Rationale: licensing problem disappears when each source is used where its
license already fits. Interface is ~30 lines and we want it anyway for failover.

## D9 — Ground truth: eBird, effort-normalized
- BACKTEST: eBird Basic Dataset (EBD), custom extract = Mourning Dove only,
  TX/OK/KS/NE. Requires a free data request + Cornell terms (no commercial
  redistribution - revisit before monetizing). Has refresh lag.
- LIVE: eBird API 2.0 (rolling ~30 day window).
- CONFIRMATION: founder's own hunt logs. n=1 but exactly on-target.

TWO CONFOUNDS THAT MUST BE HANDLED:
1. Observer effort. eBird counts people, not birds. Use COMPLETE checklists
   as denominator, normalize by duration+distance. Otherwise the model
   "discovers" that doves migrate on Saturdays.
2. Resident baseline saturation. Mourning doves are abundant residents in
   Dallas year-round, so detection FREQUENCY is pinned at the ceiling and a
   migrant pulse moves it by ~nothing. Must use mean count per standardized
   observer-hour, as a z-score vs trailing local baseline.
   Migrants don't change presence. They change DENSITY.

Rejected: eBird Status & Trends - modeled + weekly-smoothed, which deletes
exactly the daily pulse we are trying to detect.

## D10 — Runtime: GitHub Actions + repo-as-database + static dashboard
Scheduled Action -> pull weather -> score arcs -> commit results (SQLite or
Parquet) -> publish static dashboard to Pages. No server.

Primary rationale is NOT cost. Committing each forecast to git produces an
immutable timestamped record of what we predicted BEFORE the outcome was
known. That is what makes the grading loop honest and un-fudgeable. We get
it free as a side effect of the deploy mechanism.

Limits: GH scheduled Actions are best-effort (can run late) - fine daily,
disqualifying for minute-level. Repo grows monotonically - fine at our volume
(~few hundred thousand rows/yr; this is a small-data problem).

PRIVACY (hard rule): field pin coordinates NEVER get committed. Gitignored
local config or encrypted Actions secret. Committed data = arc scores only.
Upstream arcs are public weather over OK/KS/NE. The six fields are private.

---

# Phase 3 — Prototype findings (2026-09-12)

Engine runs end-to-end on live data: dove/geo.py, dove/weather.py,
dove/push.py, scan.py.

## F1 — Absolute photoperiod does NOT work as the seasonal gate
Near the equinox, day length is almost latitude-independent and the small
residual runs BACKWARDS: 33N falls through 12.5h a few days BEFORE 41N.
An absolute-daylength gate therefore opens the SOUTHERN arcs first, which
inverts the biology (northern birds leave first).
Replaced with day-of-year shifted by latitude (~Sep 15 at 33N, ~Sep 2 at
41N). Strawman constants; calibrate against EBD.

## F2 — Four scoring defects found by running it
1. Sharpness term scanned all 24h of temperature, so it scored 10/10 every
   day - it was detecting SUNSET, not fronts. Now daytime (10-18h) only,
   where a falling temperature is actually anomalous.
2. Clearing term rewarded absolute low cloud, so clear stagnant hot August
   days scored full marks - the opposite of post-frontal. Now a day-over-day
   cloud DECREASE.
3. Those two together put a ~20pt floor under every day. Signal-to-noise was
   under 2:1 (real front 38 vs dead August day 20). Now ~15:1.
4. STRUCTURAL: was averaging weather across the 5 arc points and THEN
   scoring. A front is a boundary; averaging across a 600mi arc smears it
   out of existence. Must score each point, then average the SCORES.

## F3 — First real detection (unvalidated against birds)
Sep 15 2026, Arc 4 (Nebraska): raw 47 - 11mph S-push, 10F drop, +5.0mb.
Arc 3 (Kansas) same day: raw 39. Arcs 2 and 1 stayed near zero Sep 16-18,
i.e. the boundary washed out before reaching Oklahoma. Gate correctly
suppressed the index (0.63) - mid-September, population not fully staged.

## OPEN — nothing here is validated against actual birds yet
Everything above is plumbing plus plausibility. Test 1 (does Push Index
correlate with eBird dove density anomalies) has NOT been run.
BLOCKER: eBird EBD custom extract requires a data request with human
turnaround. Submit early.

## F4 — Front tracking (dove/front.py, forecast.py)
Daily resolution is too coarse to track a boundary: arcs are ~130mi apart in
latitude and a front crosses that in hours. Passage detection runs on the
HOURLY series (wind veering southward + pressure trough + temp falling),
requires a 3-of-5 point quorum per arc, then least-squares fits passage time
against latitude to MEASURE the front's speed rather than assume one.

Two more bugs found by running it:
5. Speed fit returned 3.2 mph because it regressed across TWO unrelated
   fronts. Added cluster_fronts(): an inner arc joins a boundary only if it
   fires after the outer one and within gap_mi/7mph. Plus a 5-70mph sanity
   band on the output.
6. Index attribution was off by a day - a front clearing at 23:00 leaves its
   fingerprint on the NEXT day's daily aggregates. Now takes best index in a
   +/-1 day window.

## F5 — Arrival model: superposition of per-arc pulses
Birds do NOT ride the front in. They depart when the front clears the
latitude they are staged at, then fly south at their own pace
(~150 mi/day strawman). Each arc contributes a Gaussian pulse at its own
lead time, smeared wider for distant arcs. Big days = pulses stacking.

This produces a non-obvious and correct result: front 1 reaches Dallas
Wed Sep 16, but peak bird arrival is Fri Sep 18. The weather arrives two
days before the birds do, because the front outruns them.

## LIVE PREDICTION (made 2026-09-12, unvalidated)
Front 1: arc4 Sep14 23:00 -> arc3 Sep15 08:00 -> arc2 Sep15 21:00,
measured speed 10.5 mph (slow side - flag for validation).
Peak arrival index 43.1 on Fri 2026-09-18, secondary 31.5 Sat Sep 19.
Front 2 (arc1 only, Sep 19) -> minor bump Sep 20-21.
