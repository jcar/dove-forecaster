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

## D11 — Anchor moved north of Dallas (2026-09-12)
The single forecast location moved from downtown Dallas to a point ~44 mi
north in Collin/Grayson County, where the founder hunts. Hunting locations
and field coordinates are private and never stored here (D10). The model's
real resolution is ~25 mi, so one anchor stands for the whole area; a picker
across nearby towns would be false precision. (Since 2026-10-10 the audit
forecast uses a neutral North Texas lattice node instead - see D32.)

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
data/hunt_log.csv, a header and nothing else. The founder is not in the
field enough for their own reports to be worth anything - a couple of hunts a season is noise, and I should not have
listed it beside the wave as comparable. It exists so hunter-observed data
has somewhere to go IF volume ever arrives.
The real target is an outfitter's own reservation data: which fields filled,
how hunts went. Field-level, hunter-observed, exactly on target. That is a
relationship to build, not code.

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

## D19 — Wind at flight level, and a flight law made of physics (2026-09-21)
The flight model was fed 10 m wind. Migrating doves fly a few hundred to
~1,500 ft up; 10 m wind is surface friction - trees, terrain, buildings.
Measured across the lattice, 925hPa (~2,750 ft) runs 1.3x to 2.8x the surface
speed, averaging about double. Every arrival date was therefore biased LATE.
925hPa comes from the same request at no extra cost. Surface wind is still
fetched and is still what the conditions table shows, because that is what a
hunter feels standing in the field.

That change FORCED retuning the flight law: at flight level a front routinely
gives 20-30 mph of tailwind, and the old linear law
(25 + 13*push, capped 260) saturated at 20 - it could not tell a good front
from a great one.

Replaced with flight physics rather than a fitted line:
    ground speed = AIRSPEED_MPH (32) + tailwind
    distance     = FLIGHT_HOURS (5.5) x ground speed
with a departure ramp: below 3 mph they stage (15 mi of local drift), by
11 mph essentially the whole cohort is moving, and on a headwind under
-2 mph they sit down entirely.

A hard go/no-go threshold was tried first and rejected: it put a cliff
between 3 and 5 mph tailwind that moved an arrival by days on a 2 mph
difference. Not every bird leaves at once, so the FRACTION departing ramps.

STILL GUESSES - but better guesses. 32 mph airspeed and 5.5 hours aloft are
quantities someone can look up and argue with; an intercept and a gain were
not. Both remain uncalibrated against real birds.

EFFECT at the tracked location: peak Sep 22 (92.6) -> Sep 21 (100.7), and
birds still airborne past the window fell 94.4 -> 67.4 because they now
actually complete the flight.

## D20 — The wave panel had no latitude in it (2026-09-25)
wave.py collected 15 circles across 5 latitudes. dashboard.py then summed every
circle into one bucket - it loaded each circle's coordinates and never keyed on
them - so the panel titled "Are the birds actually moving?" could not show
movement. It also broke the project's own rule that rows are read only against
their own history. Nothing needed re-fetching; the data was on disk all along.

Same block, two more bugs: snapshots overlap by 7 days and were summed without
dedup, so Sep 21 read 93 birds when the truth was 51, with the recent edge
counted fewer times than the middle; and `counted` was dropped, so "X"-only
reports diluted the ratio. Now: newest snapshot wins per (circle, species,
day), density = birds / counted.

dove/wavetrend.py: each row minus its OWN rolling median, then lagged
cross-correlation between adjacent rows, north to south.

FIRST RESULT WAS WRONG, AND WHY. A fixed r >= 0.35 bar reported a mourning dove
"wave" at 2.4 mph - and the non-migratory collared-dove control showed equal
structure (r = 0.83, 0.56). Taking the best of 7 lags on ~14 days finds strong
correlations by chance. Replaced with a Bonferroni-over-lags, one-sided Fisher-z
threshold (r >= 0.63 at 14 days, 0.37 at 42), plus a CONTROL GATE: if collared
doves pass the same test, the result is void.

Under the corrected test (18 days): no wave for any species; control quiet.
One pair passes genuinely - Oklahoma leads north Texas by 2 days, r = 0.88
against 0.63, ~86 mi/day, inside the flight model's range. Reported as
suggestive, not as a wave.

Ladder extended to 48.5N (7 rows, 63 calls/morning); the new rows render as
"no history yet", never as zero birds.

## D21 — The flight sim had ~4 days of wind; both laws now graded daily (2026-09-25)

TRIGGER: forecasts from Sep 18-21 all called a Sep 22 arrival; from Sep 22 the
near term went to ~0 and the peak slid to Oct 5 while growing (111 -> 231).

HINDCAST on observed weather (Sep 10-25, no forecast error), home = the D11 anchor:

    peak       surface + linear law   Sep 22 (148)
               925hPa + airspeed law  Sep 21 (148)
               925hPa + linear law    Sep 21/22 split (131/135)

eBird, Collin Co.: mourning dove 2.06/hr Sep 21 -> 5.40/hr Sep 22; north Texas
wave row +3.1 on Sep 22, back to 0.0 / -0.1 on Sep 23-24. Collared-dove control
flat. So the Sep 22 call looks right, and the quiet week after it looks real.
The old law was a day closer - ONE event, not grounds to revert.

BUG FOUND: push_field was built from the 20-day DISPLAY window, which starts
only ~4 days before today. A flock leaving a band earlier had no wind to fly
on and was written off as "still airborne" (104 index points on Sep 25; 14
after the fix). push_field now uses the whole season.

ALSO: fronts whose last band crossing is > 10 days old leave the table, and a
local passage only counts as a front's arrival within 6 days of its last band
crossing - every August front had been "reaching home Sep 30". A departure
only counts as airborne if it could still be inside its 16-day flight.

DECISION: keep 925hPa + airspeed law live. Publish `arrival_challenger` (same
birds, same wind, old linear law) in every audit-trail forecast, so the
season's counts decide between them. After the fix both laws agree on the
Oct 5 peak (231 vs 216): that peak comes from the weather, not the law.

## D22 — Watch every flyway; fix how overlapping eBird pulls combine (2026-10-04)

The wave grid goes from 21 plains circles to 128 across the lower 48 (same
2.5 x 3 deg lattice, so the original 21 names and their history carry over).
384 calls a morning, ~2 minutes with the existing adaptive pacing. Every
flyway is WATCHED, including those we do not publish forecasts for, because
those counts are the only way an unpublished forecast can ever be graded.

State and flyway come from real state outlines (dove/regions.py,
data/geo/us-states.json), not bounding boxes. Flyways are the four USFWS
flyways by whole state.

FOUND: eBird's geo/recent returns ONE record per location - its latest
sighting (verified: 70 records, 70 locations, zero repeats over 30 days).
So D20's "newest pull wins" was wrong: a hotspot birded again later vanishes
from the earlier day in every newer pull. Now:
  - snapshots keep per-location records; overlapping pulls are UNIONED by
    (location, day);
  - for older aggregate-only pulls, the pull that saw the day at the MOST
    locations wins;
  - a circle's first pull is trusted only from the day before it (its
    week-long reach-back sees each spot only on its latest visit, which
    would draw a fake rising trend);
  - today is never published: it is always half-counted at 7am.

Rows and flyway heatmaps are now the MEAN OF EACH CIRCLE'S OWN ANOMALY, not
an anomaly of pooled counts. Pooling raw counts puts a step in a row the day a
new circle joins it.

## D23 — Weather straight from ECMWF open data; the site is deployed, not committed (2026-10-04)

WHY: Open-Meteo bills by location-days. Texas + Oklahoma already ran ~9k a
day against a ~10k free ceiling; the Central Flyway needs ~19k, the lower 48
~34k. ECMWF publishes the same model we pin (IFS 0.25) as free files
(CC-BY-4.0): 3-hourly to 144 h, 6-hourly to 360 h, every field we read
including 925 hPa wind. One download (~105 files' worth of byte ranges, ~45 s)
serves any number of points.

SIDE BY SIDE, same day, same history, all 152 locations:
  raw hourly       temp 0.2-0.4 F, wind 0.1-0.3 mph, cloud 0 (median |diff|);
                   surface pressure a CONSTANT 0-4 hPa offset (Open-Meteo's
                   elevation correction) - the model only uses its changes,
                   which agree to 0.3 hPa.
  fronts           every strong passage at the same hour; differences only at
                   the detection threshold.
  arrivals         140/152 same peak day (the rest: near-equal twin peaks
                   swapping, or +-1 day); curve correlation median 0.996;
                   peaks ~4% larger.
Open-Meteo's ecmwf_ifs025 is itself built from these 3-hourly files, which is
why the "coarser time steps" risk did not materialise.

BUG FOUND ON THE WAY: the disk cache merged frontal passages by exact
timestamp, so a front re-timed by a few hours in a later run was stored twice
and launched two flocks. 27% of stored passages were duplicates (3,978 ->
2,922). Merge now: stored history before the fresh series can see, fresh run
after, and never two passages inside the detector's own 36 h separation.

ALSO: each node is now stamped in its own local time zone (Mountain-time
nodes had been bucketed into Central-time days). ECMWF's horizon is 15 days
against Open-Meteo's 16; the flight sim loses its last day of runway.

Open-Meteo stays for: the single-location audit-trail run (season replay
needs 50 past days; ECMWF keeps 4), the GFS ensemble, and as an automatic
fallback for any node the ECMWF download misses.

SITE: docs/ is no longer committed. The daily job builds it and deploys it
with actions/deploy-pages. Git keeps what must be kept - the audit-trail
forecasts, eBird snapshots, and the weather history cache. If the location
build fails, restore_published.py re-publishes what is live, so a bad
morning serves yesterday instead of an empty page.

## D24 — Publish the Central Flyway; forecast every flyway in shadow; grade them all (2026-10-04)

PUBLISHED: all ten Central Flyway states (TX OK KS NE SD ND NM CO WY MT),
418 locations from real state outlines. The old bounding boxes had put
locations in Chihuahua and the Gulf; Texas + Oklahoma go 152 -> 115 honest ones.
The map widens to the whole flyway; search accepts any of the ten states.

ROUTES (dove/geo.py ROUTES): each flyway has a corridor it may slide within
and a bearing birds arrive from. Central -116..-90, due north (widened from
the CMU's -104 so a Montana corridor is centred on Montana; verified that
every location east of -100.5 gets bit-identical forecasts, and only the
west-Texas/NM sites whose corridor was pinned at -104 change). Mississippi
-98..-80 due north; Pacific -125..-108 due north; Atlantic -86..-66 from 35
deg east of north, with tailwind measured along that bearing and the flight
sim's progress scaled by cos(35). These three are a biologist's first sketch.
Band labels now come from the ground under them ("Southern Nebraska",
"Saskatchewan"), not one north-Texas hunter's names.

SHADOW: Mississippi, Atlantic and Pacific (676 locations) are forecast every
morning and NOT shown. Every location's call - published or not - is kept in
data/sitelog/ (~230 KB/day), the record grade.py scores.

THE PUBLISHING RULE (grade.py): per flyway, each forecast made 1-3 days ahead
is correlated with the nearest eBird circle's mourning-dove anomaly, circles
combined by Fisher z. PASSES needs >= 21 days of record, z >= 2.71 (p < .01
after Bonferroni over 3 leads) AND the collared-dove control below z 1.64.
Verified on synthetic records: a forecast equal to the counts passes (z 13-16);
one equal to the collared-dove counts is flagged "control"; random noise is
"no skill". The Central flyway is held to the same rule - it is published on
one verified event, and the scorecard on the page says so. Both flight laws
are scored, which is how D21's question gets answered.

HISTORY: ECMWF keeps four days, so the ~1,650 new lattice nodes started
empty. backfill_history.py spends idle Open-Meteo quota (12k location-days a
morning, published flyway first) fetching 40 days per node; the Central
Flyway was filled the same day, the shadow flyways fill over ~2-3 mornings.
A location with fewer than 21 days says so on its page.

NOT VALIDATED, AND THE PAGE SAYS SO: the north. Reservoir levels come out
ordered sensibly (Saskatchewan ~0.2-0.3, Nebraska ~0.45 in early October)
but the depletion constants are strawmen set for Texas. Billings, MT shows a
mid-October push, which is later than Montana doves usually leave. The
scorecard will say whether that is wrong.

## D25 — Ducks join; the research the engine now rests on (2026-10-04)

One app, two sections (doves Sep-Oct, ducks Nov-Jan; one engine). Central
Flyway first. Duck groups: mallards & big ducks (mallar3) | teal (gnwtea,
buwtea) | gadwall, wigeon, pintail (gadwal, amewig, norpin). Published
openly with an "untested" label until the scorecard passes (user's call).
Every model change is a CHALLENGER scored beside the live law first.

EBIRD, COLLECTION: one call per REGION per species - all 48 states + DC, plus
Canada and Mexico for the border circles - binned into the 128 circles
ourselves. Verified against the 50 km geo call: 30/32 circles identical with
states only; 4/4 border circles identical once CA and MX are added. 9 species
x 51 regions = 459 calls. Serial, with a 15-minute budget, doves first:
four concurrent requests on top of a day of testing drew HTTP 429.
CORRECTION: an all-species geo call returns one sighting per species per
circle, not per spot - useless for density. (I had told the user otherwise.)

PROFILES: dove/profiles.py holds everything species-specific. Introducing it
changed nothing: bit-identical arrivals, challenger, airborne, fronts and
band scores on all 1,094 locations against the previous commit.

RESEARCH (three passes; full reports summarised here, citations kept):
Ducks
 - WSI, Schummer et al. 2010 JWM 74:94 (doi:10.2193/2008-524), computed where
   birds LEAVE: -Tmean(C) + consecutive days Tmean<=0 + snow(cm)*0.394 +
   consecutive days snow>=2.54 cm. Worked example 2,-1,-5 C / 0,3,26 cm ->
   -2, 4, 19. Mallards decline past 7.2 (8 in Schummer 2014).
 - Latitude-dependent species models: Notaro et al. 2016 PLoS ONE
   e0167506 (mallard PC1; WSIMEAN for gadwall, wigeon, GW teal, shoveler;
   7-day max WSI for pintail). Thresholds derived from them are sensitive to
   coefficient rounding: priors only. None fit in the Central Flyway.
 - Departure night: O'Neal et al. 2018 Mov. Ecol. 6:23 - ducks left on 30%
   of nights, ~44 min after sunset; following wind aloft OR 35.2, no rain
   13.2, not overcast 2.8; P=0.76 when all favourable; cruise 490+-163 m AGL.
 - GPS: Pearse et al. 2023 Ecol Evol (first migration median 838 km;
   +166 km and +29% odds per 1 C colder minimum; +80% per cm snow later);
   Weller et al. 2022 Mov Ecol 10:1 (snow days 65% of departures; ice model
   2 d < 0 C, 1 cm per 3.3 FDD); Krementz et al. 2012 (stopovers 15.4 d);
   McDuie et al. 2019 (mallard 82.5, pintail 79, gadwall 70.6, wigeon 52 km/h).
 - Chronology: Baar et al. 2008 Waterbirds 31:394 (TX playas: blue-winged
   teal gone by October; mallard and pintail peak late winter; ice-up early
   December).
Doves
 - Band recoveries (Dunks et al. 1982 USFWS SSR-W 249; Otis et al. 2008):
   young leave first; North Texas harvest 72% local early Sep -> 27% Oct;
   migrant share KS ~38%, NE ~48%, SD ~44%, ND ~65%, OK ~15%, TX ~8%.
 - Progress 10-110 mi/day including stopovers (Taber 1930; Baskett et al.
   1993 via Birds of the World). The live law allows 420 in a day.
 - 925 hPa is underground over CO, WY, MT, NM, the TX Panhandle and western
   KS/NE; doves fly low. Use 100 m wind.
 - No published numeric dove weather trigger: push weights must be fit.
 - Urban white-winged doves mostly resident (Collier et al. 2012).
Existing systems
 - BirdCast (Van Doren & Horton 2018 Science) cannot see doves or ducks;
   lesson kept: beat a calendar-only baseline, not zero.
 - Schummer Lab weekly duck forecast: Mississippi and Atlantic only.
 - eBird Status & Trends: the calendar baseline - internal use only under its
   terms (needs the user's free key; public display needs Cornell's OK).
 - Commercial apps publish no validation.

## D26 — Wind above the ground, snow, rain, and the evening window (2026-10-04)

ECMWF fields added: 100 m wind; u/v at 1000/850/700 hPa (925 was there);
sd and rsn (snow depth = sd x 1000 / rsn - matches Open-Meteo's physical depth
to the centimetre at two snowy Alaska points); tp (as an hourly rate within
each run). Open-Meteo requests the same set. Side by side with Open-Meteo at
Dallas, Denver, Cheyenne, Amarillo and North Dakota: 100 m wind 0.1-0.3 mph,
above-ground wind 0.2-0.4 mph median.

dove/agl.py: wind at a height ABOVE GROUND, interpolated in log-pressure
through the 100 m wind and only those pressure levels above the surface that
hour. Over Denver (surface ~840 hPa) the 925 and 850 values are rejected as
underground; tested. sunset_local() (NOAA approximation) checks against the
almanac: Dallas 19:09, Denver 18:39, Bismarck 19:18 on Oct 4.

New per-day features (alongside, never altering, the live dove keys):
wind_push100 (doves fly low), night_push / night_cloud / night_rain_mm / p_eve
in the window sunset+45 min to +3 h at ~450 m AGL (ducks: O'Neal et al.
2010, 2018), tmean_c, tmin_c, snow_cm, precip_mm.

dove/freeze.py: WSI exactly per Schummer et al. 2010 Table 2 - reproduces the
paper's worked example (-2, 4, 19) as a unit test - plus WSIMEAN and the
7-day max (Notaro et al. 2016) and a wetland-ice proxy (Weller et al. 2022).

Open-Meteo history is re-stamped into each node's own time zone, matching the
ECMWF path. Backfill now also refills nodes lacking the new fields.

## D27 — Ducks: a population field on the weather lattice (2026-10-04)

Not the dove band model. Every lattice node holds a relative number of each
duck group; each night a share leaves = readiness x night gate, flies one
night south along its flyway's route, and settles across the nodes around
where that distance lands it. A hunter's forecast is what settles on their
node at dawn. The cascade (a ND freeze fills KS before TX) is emergent.

  readiness   logistic in the group's severity measure at the node's own
              latitude - mallards: WSI, threshold 4.1 (35N) -> 6.3 -> 8.5
              (45N) [Schummer 2010; Notaro 2016]; puddle ducks: WSIMEAN ~-6
              to -8; teal: WSIMEAN ~-4 to -9 plus a calendar term for
              blue-winged teal [Baar 2008; Van Den Elsen 2016]
  night gate  O'Neal 2018 logistic: wind aloft OR 35.2, dry 13.2, not
              overcast 2.8, P = 0.76 all favourable
  distance    650 km + 166 km per C of overnight cooling [Pearse 2023],
              capped at groundspeed x 11 h [McDuie 2019], log-normal spread
  start       relative numbers concentrated north of ~46N

The field needs the whole season, the weather cache keeps 40 days: the state
is checkpointed to data/duckstate/ three days back each morning and replayed
forward. Published per user's decision with a permanent "untested" banner
driven by the scorecard. Every parameter is a prior to be refit.

## D28 — The evidence-based dove challenger, and grading against the calendar (2026-10-04)

DOVE_V2 (dove/profiles.py), scored daily beside the live law and the old
linear law; it goes live only if the scorecard says it wins:
100 m wind; airspeed 39 mph; legs <= 200 mi; fly_prob 0.4 so typical
progress is 15-89 mi/day (evidence: 10-110 including stopovers); departure
ramp 40 days with a young cohort (55%) ten days ahead; lands late morning.
Not yet in v2: the resident/migrant split and a refilling dove cascade.

grade.py now scores every forecast (dove live, dove linear, dove v2, three
duck groups) per flyway, and a forecast passes only if it ALSO beats "the
calendar" - each circle's own centred 21-day mean, which peeks at the future
and so is a generous calendar and a strict bar - by z >= 1. Synthetic tests:
perfect passes (z 13.6); control-tracking flagged; random and calendar-only
both fail.

## D29 — The weather cache moves to its own branch (2026-10-04)

With the D26 fields and every flyway backfilled, data/wxcache is ~2,062 files
(~35 MB at full precision) and every one is rewritten each morning - hundreds
of MB of master history a season. Floats are now stored at 2 decimals, and the
cache lives on branch `wxcache`, force-pushed as ONE commit daily: the daily
job restores it before building and saves it after. Master keeps what is an
audit trail - forecasts, the forecast log, eBird snapshots, the duck-field
checkpoint (data/duckstate/).

## D30 — Ducks by species, rolled up to groups and "all ducks" (2026-10-09)

The user wants every duck in one view, opening into each species. The field
model now runs one profile PER SPECIES (mallard, green-winged and blue-winged
teal, gadwall, wigeon, pintail), each with its own priors from the D25
studies (Notaro et al. 2016 thresholds smoothed; blue-winged teal on the
calendar per Baar et al. 2008 / Van Den Elsen 2016).

Adding them up honestly: the field knows relative numbers only, so each
species is expressed in units of ITS OWN big push (82nd percentile of peak
arrivals across published locations). A group is the sum of its species and
"All ducks" the sum of the groups. The page leads with All ducks as one
stacked chart (fixed colours by group, validated for colour-blind separation
in both themes; light-mode contrast relieved by direct labels and the list
below), then a native <details> list per group that opens into its species -
own bars, best morning, what makes it leave, and its own scorecard status.
Phone-width screens draw the chart at phone size.

grade.py scores every layer: each species against its own eBird counts, each
group, and all ducks together.

## D31 — A front that clears after the birds land (2026-10-10)

The user asked why Dallas showed "Front hits Fri" as a dashed line on Friday
night when the birds land Friday morning. Three findings:

1. **Two weather models on one chart.** The bars and the front line come from
   ECMWF (D23). The wind tiles and the day-by-day table were fetched live from
   Open-Meteo's default, which in the US is the American model (GFS). For
   Oct 16 they disagreed by a day: GFS put the front through Dallas around
   1-3 am Friday (north 13-18 mph all day), and ECMWF stalled it just north
   (calm Friday, north wind at midnight). The page showed north-wind arrows
   under a "front Friday night" line. The live table now asks for
   `ecmwf_ifs025`, so the whole page reads one model.
2. **The line is in the right place for ECMWF.** A front that hangs up just
   north of the fields leaves calm air ahead of it, and birds that rode it
   pile up at its edge and drift in before it formally clears. The page now
   says so ("Front clears Fri night / hangs up just north of you first") and
   gives the time of day on every front label. The Sept 13 rule that names
   the next strong morning behind the front as the pick is kept, since a
   stalled front's clearing time is the least certain part of the forecast,
   but the chart no longer calls the peak "the morning to go" when the tile
   says otherwise. A slow measured front speed was tried as the stall signal
   and rejected: the tracker reports under 8 mph at 384 of 415 locations.
3. **Do birds fly past a stalled front?** The flight sim reads one wind per
   day at the flock's starting latitude, so a flock can sail through the wind
   shift into the south wind ahead of it. `simulate_arrival(substeps=N)`
   splits the day into N legs, re-reads the wind at each, and sets the flock
   down where the tailwind turns to a headwind (a day that starts without a
   tailwind still drifts as before). On the live law it moves Dallas by 2-3%,
   so it goes to the `dove_v2` challenger only (`flight_substeps=6`); the
   live dove forecast is bit-identical across all 418 Central locations.
   Larger v2 changes at some locations come from flocks landing near v2's
   16-day flight cutoff, which a few hours can push either side of - a
   known weakness of the slow v2 law, not of this change.

## D32 — No outfitter or private location in the code or on the site (2026-10-10)

The founder's own hunting spot stays a private test location, never a
public one. The code holds no named hunting locations: daily.py's audit
forecast runs at a neutral lattice node (33.75 N, 97.0 W, "North Texas
reference point"), and a local test location comes from the DOVE_HOME
environment variable, set only in the gitignored .env. The saved daily
forecasts (data/forecasts/) had the old location's name in their "home"
label; the label was replaced with "North Texas reference point (D11 anchor)".
Nothing the model claimed was changed - only that label.

## D33 — Effort-corrected counts, and the scoring rules written down first (2026-10-10)

**The hindcast.** `hindcast.py` reruns the dove forecast as of each morning
Sep 10 - Oct 7 on observed weather (418 Central locations, all three laws)
and scores it with grade.py's own scorer. Result: no skill. Live lead-1 z
-0.89 against mourning doves, -0.13 against all doves (D34); every law sits
inside the range a forecast shifted 5-20 days out of step reaches. Forecasts
slid ±1-3 days do no better, so it is not a timing offset. Against the one
effort-corrected series we hold (Dallas County complete checklists, birds per
hour, 28 days): live r +0.02; dove_v2 r +0.25 with the control at -0.23 -
noted, not acted on; 28 days cannot carry it.

**Why the test is weak, not just the model.** Only 9 of 46 Central circles
had enough data to correlate and 3 (Dallas-Sherman, Tulsa, Omaha) real
volume. Worse, the collared-dove control moved with the target at every lag:
the wave counts SIGHTINGS, so a busy birding day reads as a dove day, and a
birder who looked and saw none leaves no trace. Nothing is fit to this.

**The fix: whole checklists** (`dove/checklists.py`, its own workflow at
09:41 UTC; daily.py runs it again as a backup, which costs nothing when the
day is already saved). Each morning: the day three days back (most lists submitted by
then; any missing day within 7 is filled), every county with a hotspot
inside a Central circle (204 counties, `data/geo/checklist_counties.json`),
lists inside the circle, group checklists de-duplicated, up to 20 read per
circle per day (seeded random sample). One checklist gives doves, ducks and
the control at once, with real zeros. Test day Oct 7: 252 lists, 227 read,
163 complete and timed, 15 circles with three or more. ~430 calls, ~5.5 min.
Stored without names, IDs or coordinates (eBird terms; personal locations).

**Scoring rules for the effort-corrected record, fixed now - before the
data exists - so the bar cannot drift toward whatever the model happens to
do:**

1. Measure: birds per hour on complete (all species reported), timed,
   stationary or traveling checklists of 5 h or less; "X" counts dropped for
   that species. Doves = mourning + white-winged (D34).
2. Unit: a circle over a 3-day window centred on the target day (hunters
   read days, not hours, and single days are mostly noise); forecast is the
   3-day sum at the nearest location within 60 km. A window needs >= 6 such
   checklists or it is skipped.
3. Statistic: per-circle correlation of forecast with the log(1 + rate)
   anomaly against the circle's own centred 21-day median, combined by
   Fisher's z - and judged against the shift-null (forecast moved 5-20 days
   out of step): a pass must beat at least 95% of shifts.
4. Bars kept from D24/D28: control quiet (collared dove z < 1.64), beat the
   calendar by z >= 1, at least 21 target days. Status & Trends replaces
   the calendar when its key arrives.
5. Primary: lead 1, Central. Everything else - other leads, single days,
   state pooling, other flyways, duck species - is exploratory and labeled
   so; a law goes live only on the primary.

**Past seasons** run through the same scorer when the eBird Basic Dataset
arrives (requested 2026-10-10); its checklists map onto the same row format.
Weather for them needs an archive source (the cache holds 40 days).

## D34 — Doves are one bird (2026-10-10)

The user: "A hunting opportunity is a hunting opportunity." Mourning and
white-winged doves are counted, shown and graded together as "doves", with
the species one tap down; neither is favoured.

- eBird: `COMBINED` in dove/ebird.py. Every circle-day gets a "doves" series
  (and "ducks", for the same reason): birds summed; counting stops taken as
  the most any one species was counted at (the older pulls cannot tell
  distinct stops apart; same rule every day keeps each circle's normal
  comparable). White-wings are 30-50% of the doves in the North Texas circle.
- Page: the map, the latitude heatmap and "Doves near you" lead with All
  doves. "By species" splits the near-you line; the species there share the
  combined line's counting stops so they add up to it (each on its own stops
  put white-wings above all doves - true, and useless).
- Grading: the dove forecast is scored against all doves.
- Model: same numbers; the profile says "Doves". Its flight and departure
  settings come from mourning-dove studies - white-wing movement is barely
  studied - and the page says so. The scorecard is where a white-wing
  mismatch would show.

## D35 — The site is the Central Flyway, and only that (2026-10-10)

The user: focus on the Central Flyway; show nothing outside it on any map.

- Both maps (the moving forecast and the eBird counts) share one projection
  fitted to the ten Central states' outlines (`flyway.map_fit()`, 560 x 871;
  the old box ran to the Mississippi and the count map was the lower 48).
  Every layer - wind, fronts, forecast dots, count circles, freeze line - is
  clipped to the ten states, so a border circle or a front is cut at the
  flyway's edge rather than drawn past it.
- The count map, latitude heatmap, "near you" and the scorecard show Central
  only; the flyway buttons and the "watched" labels are gone.
- Behind the scenes the other flyways are still forecast, pulled from eBird
  and graded (D24). Nothing of them is shown. Whether to keep paying for
  them (eBird calls, build minutes) is the user's call.

## D36 — The hidden flyways are switched off too (2026-10-10)

With the site Central-only (D35), the user chose to stop paying for the
other three flyways behind the scenes. Forecasts, weather, history backfill,
eBird counts and grading now cover the Central Flyway alone:

- build_sites.py and backfill_history.py: Central locations only (418), so
  the weather lattice is the 862 nodes they read, not 2,062. Cached weather
  for the rest is pruned from the wxcache branch on the next build.
- eBird species pull: the 46 Central circles, from the regions they reach
  into - ten Central states, Iowa and Minnesota (border circles), Mexico
  (Rio Grande Valley): 13 regions x 10 species = ~130 calls, down from 459,
  which had started to outrun its 15-minute budget.
- grade.py: Central only. The duck checkpoint drops nodes the lattice no
  longer carries.
- The shadow-flyway records already saved (Oct 4-10) stay in the repo. The
  machinery stays too: adding a flyway back is one list in build_sites.py,
  one in dove/wave.py, one in grade.py - and its scorecard starts from zero.
