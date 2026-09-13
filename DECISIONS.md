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

## F6 — CI verified live (2026-09-12)
Repo: jcar/dove-forecaster (private). First green run 34724937813, bot
commit 7f06cda "forecast 2026-09-12" landed on master.

Confirmed: workflow-level `permissions: contents: write` DOES override a
repo whose default_workflow_permissions is "read". No settings change needed.

GOTCHA: GitHub did not index the workflow from the repo-creation push, nor
from a later unrelated commit. Only a push that MODIFIED .github/workflows/
daily.yml itself caused registration (0 workflows -> 1). Expect this on the
next new repo.

Hardened while in there: concurrency guard (manual dispatch vs the 08:00
scheduled run) and `git pull --rebase --autostash` before push. Without the
rebase, two overlapping runs collide on non-fast-forward and silently drop a
forecast - a hole in the audit trail exactly on the busy days.

DETERMINISM: a clean Ubuntu runner reproduced the local forecast exactly -
same fronts, same 10.5 mph, same 43.2 peak on Sep 18. Only generated_at
differed. Given the same weather input the engine is deterministic.

KNOWN MINOR: "today" comes from date.today(), which is the runner's TZ (UTC
in CI, Chicago locally). Harmless at the 13:00 UTC schedule since that is
08:00 CDT on the same calendar date. Would mislabel if the cron ever moved
near UTC midnight. Front/arrival math is unaffected - those are naive
America/Chicago timestamps throughout and round-trip consistently.

## F7 — ERA5 backtest, 11 seasons (2015-2025). METEOROLOGY VALIDATED.
Pooled front speeds, n=261:
  p10 9.1 | p25 13.2 | median 19.9 | p75 34.5 | p90 48.6 mph
  season medians 16.4-28.4 (tight across 11 independent seasons)
CONCLUSION: passage detector is NOT biased low. The live 2026-09-12 front's
10.5 mph sits ~p15-p20 - slow, but 20% of fronts are slower than 12 mph.
The committed arrival dates survive.

Fronts by arcs swept, per season:
  1 arc 25.0 (local wind shifts, noise - can never resolve a speed)
  2 arc 15.3 | 3 arc 8.5 | 4 arc 6.9
6.9 full four-arc sweeps/season matches the Phase 1 guess of "8-12 times a
season" that the product would have something to say. Single-arc detections
are noise by construction; the product keys on multi-arc chains only.

Median peak-index date: arc4 09-25, arc3 09-28, arc2 10-03, arc1 10-11.
A clean south-propagating wave - BUT the gate was configured to open arc4
~13 days before arc1, so most of that 16-day offset is the gate doing as
told, not an independent finding. Confirms the machinery composes. Does
NOT confirm the timing is right.

Reservoir trajectory (arc 4, median): Sep15 0.91, Oct1 0.58, Oct15 0.33,
Nov1 0.17, Nov15 0.10. Plausible; unconfirmable without bird data.
NOTE: an earlier claim in-session that ambient non-front days were draining
the reservoir was wrong, and the test for it was invalid (arc 4 appears in
so many fronts that a +/-1 day window covers most of the season).

## OPEN — everything checkable without birds is now checked
Remaining uncertainty is all downstream of the eBird EBD extract:
reservoir depletion rate, bird ground speed (150 mi/day strawman), pulse
width, gate constants, and component weights. STILL BLOCKED on the data
request.
Known minor: 3+ arc fronts average 6 days apart but median gap is 4, so
some single boundaries are likely being split into two events.

## F8 — Dashboard (D6 delivered)
dashboard_template.html + dashboard.py -> docs/index.html, regenerated by the
daily Action after daily.py and committed alongside the forecast.

Data-viz decisions, validated not eyeballed:
- Ran the palette validator. First choice (orange/aqua/magenta) FAILED both
  modes - normal-vision dE 12.9 light, CVD dE 1.6 dark. Fell back to
  reference categorical slots 1-3 (blue/orange/aqua), which PASS all-pairs in
  both modes. Aqua's light-mode contrast WARN is relieved by direct labels on
  every series.
- Heatmap uses the documented blue sequential ramp, inverted for dark mode
  (low value sits near the surface in BOTH themes - never flip a light ramp
  onto a dark ground).
- Arcs render north-at-top so the heatmap reads like the country it describes.
- Component breakdown is a tooltip, not a 5-colour stacked bar. Not
  everything is a chart.

NOT enabling GitHub Pages. Pages on this repo would put the dashboard on a
public URL. It carries no field pins (arc weather and eBird are public data),
but the repo was made private deliberately and that is the founder's call to
reverse, not mine. The Artifact serves the "see it" need privately.

## F9 — API 2.0 CANNOT backfill history economically. D9 stands.
The eBird key unlocked the LIVE layer only. It does not supersede the EBD.

Why: `historic` dedupes to one record per species, so it gives presence, not
abundance. Abundance requires product/lists + a per-checklist fetch, i.e.
~25-40 calls per day of history. Three seasons = ~7,000 calls; eBird
throttled us into a backoff loop that produced ZERO days in several minutes.
Adaptive pacing (honor Retry-After, ramp the global pause, drift back down)
was added and is correct, but it cannot make 7,000 calls cheap.

Ongoing cost of grinding on it: the DAILY job needs eBird headroom. Burning
the rate limit on a backfill that will not finish risks the forward grading
that does work. Backfill stopped deliberately.

WHAT WORKS: live layer, ~30 calls/day, effort-normalized, 3 species. Now
wired into daily.py (non-fatal on failure — a throttled eBird must never
cost us the weather forecast).

CRITICAL PATH: the EBD data request is back on it, for historical Test 1.
Near-term evidence comes from grading FORWARD, one front at a time.

## OPS MISTAKE — deleted cache before regenerating
Removed data/backtest/2023-2025.json intending to re-run with `events`
stored, then immediately hit an Open-Meteo 429. Those three seasons are gone
until the limit resets (12 calls to restore). Should have written new files
and swapped. 2015-2022 intact.
Also: the `events` field turned out unnecessary — test1.py reconstructs
arrival by CONVOLUTION over arc_scores, which needs nothing but data we
already store, and doesn't inherit the front detector's thresholds.

## D11 — Anchor moved to the Dove Blasters corridor (2026-09-12)
Founder hunts Dove Blasters, a North Texas day-hunt/membership outfit.
Public info: Collin + Grayson County properties around Anna, Melissa,
Van Alstyne and Howe (US-75 corridor). Named fields (Big Boy, Wildcat,
Cowboy, Flat Top, Roadhouse, Sinbad) exist but exact coordinates are
members-only behind their app - NOT guessed, not stored.

Anchor: 33.391N -96.579W, the centroid of those four towns. ~44 mi north
of downtown Dallas, which every earlier forecast in this project used. All
their properties sit within ~25 mi of the centroid, which is well inside
this model's real resolution - so ONE anchor covers the whole operation.
Deliberately did not build a picker across the four towns: their forecasts
would differ by less than the model's error, which is false precision.

Effect of the move: front speed on the live boundary re-measured 13.5 mph
(was 10.5 from Dallas), front reaches the fields Sep 16 15:04 (was 22:48),
peak arrival index 53.9 (was 43.2). Peak day unchanged at Sep 18.
Earlier forecasts were running slightly LATE for these fields.

Bands re-derived from where the sample points actually land now:
  1  150 mi  Central Oklahoma    OKC / Shawnee / Muskogee     1 day
  2  300 mi  Southern Kansas     Wichita / Ponca City         2 days
  3  450 mi  Central Kansas      Salina / Hays / Topeka       3 days
  4  600 mi  Nebraska & Plains   North Platte / Norfolk       4 days

CONCERN: band 4 at +/-45deg and 600 mi now spans 104.5W to 88.7W - eastern
Colorado to central Illinois. Illinois birds go down the Mississippi flyway,
not to North Texas, so the eastern edge of band 4 is probably contributing
noise. Candidate fix: narrow the far cone or skew it west. Not yet done.

If exact field coordinates are ever wanted, they go in gitignored
fields.json per D10 - never committed.

## F10 — Cone geometry was WRONG. Replaced with a flyway corridor.
Two defects in D4's concentric cones:

1. FLYWAY LEAK. At +/-45deg and 600 mi the far band spanned 104.5W to 88.7W -
   eastern Colorado to central Illinois. Illinois doves are Eastern
   Management Unit and go down the Mississippi; they were never coming to
   North Texas. We were sampling weather over birds that are not ours.
2. LATITUDE SMEAR (the worse one). Points inside a single cone band sat at
   DIFFERENT latitudes. Front tracking regresses passage time against
   latitude, so mixing latitudes inside one band corrupted the very
   measurement the arrival date depends on - and biased speeds LOW.

Replacement: each band is a CONSTANT-LATITUDE segment across the Central
Flyway corridor.
  - band k at home_lat + 150k/69 degrees north
  - half-width = min(210 mi, 0.7 * north_mi) - the funnel widens with
    distance until it hits the flyway edges, then stops. Close in, country
    200 mi east of you is beside you, not upstream.
  - clipped to FLYWAY_W -102.0 / FLYWAY_E -92.0 (CMU working bounds)

Now: band1 Oklahoma 35.57N, band2 S Kansas 37.74N, band3 N Kansas 39.91N,
band4 Nebraska & Iowa 42.09N. Every point inside the CMU.

EVIDENCE THE FIX IS REAL: the live front's measured speed went
10.5 (Dallas + cone) -> 13.5 (corridor anchor + cone) -> 15.0 mph
(corridor anchor + latitude bands), converging toward the 19.9 mph
historical median as the geometry got honest. The "slow front" reading
earlier in this session was substantially a geometry artifact.

## STALE — the 11-season validation must be re-run
F7's front-speed distribution (median 19.9, n=261) was computed with the
old cone. It is not evidence for the current geometry. Blocked on an
Open-Meteo 429; ~44 calls when the limit clears. Dashboard now says so
rather than claiming a validation it no longer has.

## F11 — Extrapolated front ETA was 2.5 DAYS EARLY. Now detected, not guessed.
Adding local field conditions (option A) immediately caught a real bug.

front_speed_mph measured the boundary at 15.8 mph across the northern bands
and linearly extrapolated 600 mi to the fields -> ETA Wed Sep 16 14:00.
The local hourly forecast showed south winds and 95-100F straight through
Thursday. No front. The actual wind shift is Fri Sep 18 19:00 (NNE, then
70F by Saturday dawn) - a 25F drop, and the strongest of four detected
local passages by a wide margin (strength 26.0 vs 13.8-17.5).

Real average speed to the fields: 4.2 mph. It shed ~75% of its speed
pushing into September heat in Texas. Linear extrapolation from the fast
northern segment is simply wrong for this geography.

FIX: run the SAME frontal_passages() detector on the hunter's own hourly
series and match each tracked boundary to the strongest local passage after
its last band crossing. reaches_home is now measured. The extrapolation is
kept as eta_extrapolated so the deceleration stays visible.

## F12 — The biggest bar is not the best morning
Arrival peaks Fri Sep 18 (58) but Friday MORNING is pre-front: 80F, west
wind. Saturday morning is 71F behind a NNE wind with 52. For an actual hunt
Saturday is the better morning, and the headline was pointing at Friday
because it read the tallest bar.

Headline now checks whether the front clears before the peak morning and
recommends the morning after when it is materially cooler and carries at
least 60% of the birds. Deliberately NOT a blended score - we have no way
to validate weights on comfort vs bird count, and inventing one would be
the same false precision as showing "43.2".

## OPEN — the arrival model does not know the front stalled
Birds fly a constant 150 mi/day regardless of whether the tailwind held.
This front decelerated from 15.8 to 4.2 mph; real doves riding it would
likely stall too, which would push arrivals later than we predict. The
model currently lets birds outrun a dying front. Needs the bird speed to
depend on conditions en route. Flagged, not fixed.

## D12 — Field conditions (option A) shipped
dove/local.py: legal light (TX dove, 1/2 hr before sunrise - surfaced as
guidance with a TPWD verify note, never as authority), sunrise/sunset,
and morning/evening windows of temp, wind speed, gusts, direction, rain.
Wind direction uses a CIRCULAR mean - averaging 350 and 10 arithmetically
gives 180, due south, the exact opposite of the truth.
North-component winds bolded on the dashboard: post-frontal air is what
you want, and doves land into the wind, so set up with it at your back.

## F13 — FIXED: birds now fly on the wind they actually get
The flat 150 mi/day assumption let birds outrun a dying front. Replaced with
a day-by-day march south:

    daily_mi = clamp(25 + 13 * southward_push_mph, 0, 260)

Each departure starts at its band's latitude and advances one day at a time.
The tailwind is read from the wind field we already build - the four band
latitudes plus the fields - linearly interpolated to wherever the bird has
got to. Pulse width now scales with flight length (0.6 + 0.12*days), because
a long interrupted flight arrives more smeared than a short clean one.

Live example, Nebraska birds leaving after the Sep 14 front:
  Sep 15  42.1N  +13.1 mph  flew 195 mi   riding the front
  Sep 16  39.3N   +3.7 mph  flew  74 mi   front stalling
  Sep 17  38.2N   -0.5 mph  flew  18 mi   HEADWIND - they sit down
  Sep 18  37.9N  +10.9 mph  flew 167 mi   next push, airborne again
  Sep 19  35.5N   +7.3 mph  flew 120 mi
  Sep 20  33.8N   +4.1 mph  LANDS
They stall over southern Kansas and catch the following push. That is dove
behaviour, and the flat model could not produce it.

EFFECT: peak moved Fri Sep 18 -> Sat Sep 19, and the curve spread out
(old 20.5/57.5/52.0/11.9 -> new 6.9/32.3/46.2/27.4/8.9). The new peak also
lands on the better morning independently: Sat is 71F behind a NNE wind,
Fri was 80F pre-front. Two different parts of the model agreeing is weak
evidence, but it is the first time they have.

NEW GUESSES INTRODUCED (all uncalibrated, all set the arrival day):
BASE_MI_PER_DAY 25, PUSH_GAIN 13, MAX_MI_PER_DAY 260, and the assumption
that birds stop nearly dead on a headwind. Surfaced on the dashboard.

## D13 — Weather precision (2026-09-13)
1. MODEL PINNED. We were silently taking Open-Meteo's default blend. Now
   ecmwf_ifs025 explicitly - strongest global model for frontal timing in
   the 3-10 day window, which is the only thing this forecast rests on.
   An unpinned blend means a forecast shift can be a model swap rather than
   a weather change, and you cannot tell which.
   NOTE: pinning MOVED THE ANSWER. ECMWF disagrees with the old blend about
   when fronts cross Nebraska - band 4 went from Sep 14 23:00 to Sep 12
   01:00. Every number produced before today came from an unknown blend.

2. ENSEMBLE CONFIDENCE. 31 GFS members, frontal detector run on each.
   Front 1: 31/31 agree, detected Sep 15 21:00, ensemble median Sep 16
   00:00, spread 23h. Front 2: 31/31, detected Sep 20 23:00, median
   Sep 20 20:00, spread 40h.
   AGGREGATION TRAP (hit it first time): taking each member's STRONGEST
   front compares unrelated weather systems between members and reported
   an 8-day spread that was pure artefact. Must anchor on the deterministic
   estimate and take each member's nearest passage within +/-48h.

3. DENSER SAMPLING: 5 -> 9 points per band, quorum scales to 5-of-9. Same
   request count (batched). Verified this is NOT what moved the answer -
   5 and 9 points agree within a couple of hours on every band.

## F14 — FIXED: the sim was inventing calm past the wind horizon
push_at() returned 0.0 for dates outside the wind field, so birds that were
still flying at the edge crawled in at 25 mi/day on fabricated weather -
producing a confident arrival built on nothing. It now returns None and the
flight returns None, counted as still_airborne rather than landed.
Wind horizon raised to 16 days (Open-Meteo max) to give the sim runway, and
the display window to 14 days.

## F15 — ECMWF says the birds stall out
Not a bug. The Oklahoma band shows SOUTHERLY headwinds nearly every day
Sep 13-21. Birds released off the Sep 12 front reach southern Kansas and
sit. Arrival now peaks Sep 23 (50.6) rather than Sep 19.
The answer moved four days between yesterday and today. Causes: the model
pin, and the wind-driven flight meeting real headwinds. That swing is
itself information about how much to trust a 10-day dove forecast.

## D14 — Flyway wave accumulator (2026-09-13)
dove/wave.py. 13 circles (3 across each band + the fields) x 3 species,
50 km radius, ~39 calls/morning, ~15s. Uses data/obs/geo/recent, which
returns every recent sighting in a radius in ONE call - no checklist walk,
so this is sustainable forever where the historical backfill was not.

WHY A WAVE, NOT A COUNT: a single county rising is weak - observer noise
fakes it. A rise that PROPAGATES SOUTH band by band, in the order and at
the speed our fronts predict, is migration or nothing. Birders in Nebraska
and Texas do not coordinate their weekends. It also measures the wave's
SPEED, which is a direct test of the 150 mi/day flight assumption.

RAW COUNTS ONLY. We store birds, locations and counted-records per circle
per species per observation date, never a derived index. The right
normalisation is unsettled, and raw means we can revise it later without
re-fetching a season we cannot get back.

CRITICAL: counts are NOT comparable between bands. First snapshot showed
home with 50 reporting locations against 4-8 in Nebraska - that is pure
birder density, not birds. Each band must be read against its OWN history.
Northern bands are thin (4-8 locations), so the signal up there will be
noisy; this needs weeks, not days.

SANITY CHECK PASSED: white-winged dove returned 0 at every northern circle
and 153 at home. Whitewings are a southern bird, absent from Kansas and
Nebraska. The data is real.

## D15 — Hunt log: built minimal, deliberately
data/hunt_log.csv, a header and nothing else. Founder was straight that he
is not in the field enough for his own reports to be worth anything, and he
is right - a couple of hunts a season is noise, and I should not have
listed it beside the wave as comparable. It exists so hunter-observed data
has somewhere to go IF volume ever arrives.
The real target is Dove Blasters' own reservation data: half a dozen
properties, which fields filled, how hunts went. Field-level, hunter-
observed, exactly on target. That is a relationship to build, not code.

## F16 — FIXED: the reservoir never actually ran in the live forecast
D5 claimed a finite northern population that depletes across the season and
never refills - "first hard front of the fall >> the fourth identical one".
It worked in the backtest (one pass over 92 days) and had NEVER worked live:
engine.run() built a fresh Reservoir() at 1.0 on every run and drained it
only across the ~19 day fetch window. So it measured "was there a front this
week", not "how much of the fall has already happened". By November it would
have reported the north as untouched and over-forecast every late front.

Fix: `season_past_days()` - replay from Aug 15 each morning (Open-Meteo
serves up to 92 past days in one request, verified). Drain across the full
season; publish arc_scores for the last 20 days only, so a correct reservoir
does not bloat the payload. No stored state, so it self-heals after any
missed run.

RESULT (2026-09-13), and the latitude ordering was NOT programmed in:
  Nebraska & Iowa   0.975 -> 0.638     drains first and hardest
  Northern Kansas   0.994 -> 0.709
  Southern Kansas   1.000 -> 0.800
  Oklahoma          1.000 -> 0.898     barely touched
The gate opens earlier at northern latitudes, so northern fronts count and
southern ones do not yet. The migration wave appears in the depletion by
itself - an independent check that gate and reservoir compose correctly.

Side effect: front speed re-measured 19.8 mph (was 37.5 on the short window),
landing on the 19.9 historical median. Peak 50.6 -> 47.0, still Sep 23.

## D16 — No hunting regulations, by decision
Founder: "I do not want to bloat this and concern ourselves with hunting
regulations. This is not what this app is about."
Multi-state would have meant Texas shooting hours under a Kansas label, and
a model recommending a morning where the season is closed. Texas alone has
three zones. Sunrise/sunset stay (astronomy, always true); legal hours belong
to the state agency. LEGAL_LIGHT_OFFSET_MIN deleted.

## OPEN — front clustering still splits boundaries
Today front 1 covers bands [4,3,1] and front 2 is band [2] alone. A boundary
cannot skip a band. Known issue since the F7 gap analysis; not chased yet.

## D17 — One shared weather lattice (dove/grid.py)
350 locations x 4 bands x 9 points = 12,600 weather points a day, naively.
But locations 50 mi apart look at nearly the same country upstream. Two
ideas collapse the cost:

1. ONE LATTICE, 0.75 deg rows x 0.50 deg columns. Band distances changed to
   155.25/310.50/465.75/621.00 mi - whole multiples of the row spacing
   (2.25/4.50/6.75/9.00 deg) - so band_lat = snapped_user_lat + offset is
   ALWAYS another lattice row exactly. This matters because front_speed_mph
   least-squares-fits passage time against LATITUDE; any snapping jitter on
   that axis corrupts the measured speed. 3.5% further than the old round
   numbers, far inside model error.

2. CACHE DERIVATIVES, NOT RAW SERIES. frontal_passages costs ~22 ms/point and
   raw hourly for a full lattice is hundreds of MB. Each point is fetched,
   reduced to daily_features + frontal_passages, and the series discarded.
   Split arc_passage_from() out of arc_passage() so cached passages can be
   reused by every location whose band touches that point.

   Sound because the band score FACTORISES: score_day gives
   index = raw * gate * reservoir, and within one band `gate` (a function of
   that band's latitude and the date) and `reservoir` are identical across
   all points. So mean(index) == mean(raw) * gate * reservoir algebraically.

3. SELECT LATTICE COLUMNS, don't snap generated points. First attempt
   generated 9 even points then snapped them - several collapsed onto the
   same node and the quorum counted one station repeatedly, the same false
   agreement as F10's collapsed window. Front speed came out None. Now the
   window selects the columns inside it, so every point is a distinct node
   and the count varies with width (8 columns for a 217 mi band, 17 for
   420 mi) - honest, since a narrow band really does have fewer stations.

VERIFIED: lattice-sourced output matches direct-fetch EXACTLY for the tracked
location on arcs, arc_scores, fronts, arrival and still_airborne. One request,
56 unique points, 4.7s.

## F17 — Open-Meteo bills by LOCATION-DAYS, not by HTTP request
The whole "16 requests covers the flyway" result was true and irrelevant.
Batching 200 coordinates into one call saves round-trips and nothing else:
one call for 200 points over 45 days counts as ~9,000. Rate-limited on the
second batch of the first full build.

Measured: full flyway as designed = 39,555 location-days today, 94,932 by
mid-November. Throttling started somewhere near 9,000.

THREE FIXES, in order of how much they bought:

1. PAST WEATHER NEVER CHANGES. PointCache now keeps per-node daily_features
   and frontal_passages on disk forever (data/wxcache, gitignored) and only
   fetches one new past day plus the forecast window. Without this the daily
   cost grows all season.
2. COARSER LONGITUDE ONLY. LON_STEP 0.50 -> 1.00 deg. Latitude spacing is
   untouched, deliberately: front_speed_mph fits passage time against
   LATITUDE, so jitter there corrupts the measured speed, while longitude
   only samples across the corridor. 1 deg still gives 8 independent
   stations per 420-mile band.
3. LOCATIONS ARE LATTICE NODES. Location longitudes moved onto the weather
   lattice, so each site's own series - which is model-critical, feeding the
   DETECTED front arrival and the southern end of the wind field - comes free
   from the band fetch instead of a second 436-point request. Display-only
   extras (gusts, rain %, sunrise) are genuinely presentational and move
   client-side to the hunter's exact coordinates.

Result: 328 sites, 521 nodes, ONE fetch, ~9,378 location-days/morning
(from 12,532 with a separate local fetch). Payload 3,470 B/location.

REJECTED: NWS as the bulk source. Free, unlimited, public domain, US-only -
but api.weather.gov gridpoints carry temperature, windSpeed, windDirection
and skyCover and NO PRESSURE. That is 20 of 100 Push Index points and our
cleanest frontal discriminator (11 and 9 points on the real front, zero on
quiet days). Verified against the live API before rejecting.

## OPEN — licensing
Open-Meteo's free tier is non-commercial. One hunter's private dashboard sat
comfortably inside that; a public multi-state site is a greyer area. Founder
chose to coarsen and stay free for now. Revisit before this carries ads,
signups, or money. D8 flagged this risk when the sources were chosen.

## D18 — Publish for TX+OK; WATCH the whole system (2026-09-13)
Founder: no monetization intent (settles the non-commercial licensing
question), and happy to shrink scope - "for the most part I hunt in Texas" -
but explicitly wants the wider system still modelled, because that is where
the reservoir lives.

That distinction is exactly right and costs nothing: bands reach 155-621 mi
north of every site regardless, so shrinking the PUBLISH set does not shrink
the WATCH set at all. 152 TX+OK sites still drive a lattice spanning
26.25N to 45.75N - south Texas to South Dakota.

COUNTER-INTUITIVE: shrinking does NOT buy finer resolution. Texas-only at
0.5 deg longitude costs 12,528 location-days - WORSE than the full flyway at
1.0 deg (9,378) - because the lattice dominates: a 420-mile corridor has to
be sampled whether one hunter reads it or three hundred do. So the saving was
taken as headroom instead.

  152 sites, 371 nodes, 6,678 location-days/morning (26% under the limit)
  nearest-site error 10-33 mi, far inside model resolution

SITE_STATES in flyway.py is the single knob; adding a state extends coverage
and nothing else changes.
