"""What makes a forecast about ONE kind of bird (D25).

Everything species-specific that used to be a module constant - which wind,
which hours, how fast and how far they fly, when the season opens, what
makes them leave, how the north drains - lives in a Profile. The engine is
the same for every bird; the profile is the biology.

The DOVE profile holds exactly the constants the dove forecast ran on before
this file existed, so introducing it changed no dove number (verified by the
bit-identical regression across all 1,094 locations). Changes to dove
biology arrive as a separate challenger profile and go live only when the
scorecard says they win.
"""
from dataclasses import dataclass, field

from .geo import BANDS
from .push import photoperiod_gate


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    species: tuple                       # eBird codes this forecast predicts
    control: str = "eucdov"              # does not migrate; measures birders
    # which daily feature is "the tailwind they fly on" (push.daily_features)
    push_key: str = "wind_push"
    # flight law, see front.flight_law
    airspeed_mph: float = 32.0
    flight_hours: float = 5.5
    go_threshold_mph: float = 3.0
    full_go_mph: float = 11.0
    drift_mi: float = 15.0
    max_mi_per_day: float = 420.0
    fly_prob: float = 1.0                # share of a flyable day spent flying (expected value)
    arrival_hour: int = 8
    flight_substeps: int = 0             # >0: re-read the wind along the day's path (front.simulate_arrival)
    season_start: tuple = (8, 15)        # (month, day) the reservoir replay starts
    reservoir_k: float = 0.25
    bands: tuple = tuple(BANDS)
    gate: object = field(default=photoperiod_gate, compare=False, repr=False)


DOVE = Profile(key="dove", name="Mourning dove", species=("moudov",))


def _gate_v2(lat, doy):
    """Band-recovery evidence (Dunks et al. 1982; Otis et al. 2008):
    departures spread over 30-45 days, young birds ~1-2 weeks ahead of
    adults. Same opening (day 258 at 33 N, 1.6 d per degree - roughly
    confirmed), a 40-day ramp, and a young cohort (55% of the fall flight,
    age ratio ~1.3-2.2 young per adult, Seamans 2025) ten days early."""
    return (0.55 * photoperiod_gate(lat, doy + 10, ramp_days=40)
            + 0.45 * photoperiod_gate(lat, doy, ramp_days=40))


# The dove model corrected by the published evidence (D26/D28). A CHALLENGER:
# scored daily beside DOVE, live only if the scorecard says it wins.
DOVE_V2 = Profile(
    key="dove_v2", name="Mourning dove (evidence-based challenger)", species=("moudov",),
    push_key="wind_push100",        # doves fly low; 925 hPa is underground on the High Plains
    airspeed_mph=39.0,              # radar 65 km/h (Birds of the World); Taber 35-40 mph
    flight_hours=5.0,               # one leg <= ~200 mi
    max_mi_per_day=200.0,
    fly_prob=0.4,                   # flocks "dally ... for several days" (Taber 1930):
                                    # average progress lands in the evidenced 10-110 mi/day
    arrival_hour=11,                # a dawn start plus a ~5 h leg lands late morning
    flight_substeps=6,              # D31: come down at a stalled front, not past it
    gate=_gate_v2)

PROFILES = {p.key: p for p in (DOVE, DOVE_V2)}


# ---------------------------------------------------------------------------
# Ducks (D27). A different engine (dove/duck.py: a population field on the
# weather lattice) with these parameters. Every number is a PRIOR from the
# literature cited beside it, to be refit against eBird by the scorecard; none
# of these studies was fit in the Central Flyway.

@dataclass(frozen=True)
class DuckGroup:
    key: str
    name: str
    species: tuple
    control: str = "eucdov"
    # readiness: logistic in a severity measure; threshold may vary with lat
    measure: str = "wsi"             # wsi | wsimean | wsi7max
    theta: tuple = ((35.0, 0.0),)    # (lat, threshold) pairs, linear between
    slope: float = 1.5               # logistic width, index units
    # calendar term for early migrants (blue-winged teal): day of year the
    # departure probability peaks at 45 N, shifting later 2 d per degree south
    calendar_peak_doy: float = None
    calendar_width_d: float = 14.0
    groundspeed_kmh: float = 80.0    # McDuie et al. 2019 GPS medians
    night_km: float = 650.0          # Pearse et al. 2023: first moves median 838,
                                     # later 488 km; 650 between them
    km_per_c_drop: float = 166.0     # Pearse et al. 2023
    # breeding/staging distribution at season start: share of birds by
    # latitude, logistic centred here (prairie potholes ~45-55 N)
    north_centre: float = 46.0


DUCK_MALLARD = DuckGroup(
    key="duck_mallard", name="Mallards & big ducks", species=("mallar3",),
    # Schummer et al. 2010: declines past WSI 7.2; Notaro et al. 2016 mallard
    # model puts the zero-crossing ~4 at 35 N rising to ~8.5 at 45 N.
    measure="wsi", theta=((35.0, 4.1), (40.0, 6.3), (45.0, 8.5)),
    groundspeed_kmh=82.5)

DUCK_PUDDLE = DuckGroup(
    key="duck_puddle", name="Gadwall, wigeon & pintail",
    species=("gadwal", "amewig", "norpin"),
    # Notaro 2016 WSIMEAN models (gadwall ~-7, wigeon ~-9 to -11; pintail on
    # the 7-day max WSI ~0). One group, one measure: WSIMEAN at -7 is "a 7-day
    # mean near 7 C" - these birds leave well before the hard freeze.
    measure="wsimean", theta=((35.0, -6.0), (40.0, -7.5), (45.0, -8.0)),
    groundspeed_kmh=70.6)

DUCK_TEAL = DuckGroup(
    key="duck_teal", name="Teal", species=("gnwtea", "buwtea"),
    # Green-winged: Notaro 2016 WSIMEAN ~-8. Blue-winged: no weather model
    # (Van Den Elsen 2016: photoperiod); Texas playas see them Aug 16-Sep 15
    # and almost none by October (Baar et al. 2008) -> calendar term.
    measure="wsimean", theta=((35.0, -4.0), (40.0, -8.0), (45.0, -9.0)),
    calendar_peak_doy=245.0, calendar_width_d=14.0,
    groundspeed_kmh=60.0)        # cinnamon teal 63.5 as the proxy

DUCK_GROUPS = {g.key: g for g in (DUCK_MALLARD, DUCK_PUDDLE, DUCK_TEAL)}

# One profile PER SPECIES (D30), so the page can open a group and show each
# bird. Thresholds are the species' own priors from the same studies - the
# Notaro et al. 2016 values are sensitive to coefficient rounding, so they are
# smoothed here and refit by the scorecard. The groups above are now roll-ups.
DUCK_SPECIES = {g.key: g for g in (
    DuckGroup(key="mallar3", name="Mallard", species=("mallar3",),
              measure="wsi", theta=((35.0, 4.1), (40.0, 6.3), (45.0, 8.5)),
              groundspeed_kmh=82.5),
    DuckGroup(key="gnwtea", name="Green-winged teal", species=("gnwtea",),
              # Notaro 2016 WSIMEAN zero-crossings ~-3.8 (35N), -8.0 (40N), -9.2 (45N)
              measure="wsimean", theta=((35.0, -4.0), (40.0, -8.0), (45.0, -9.0)),
              groundspeed_kmh=63.5),
    DuckGroup(key="buwtea", name="Blue-winged teal", species=("buwtea",),
              # no weather model (Van Den Elsen 2016: photoperiod); TX playas
              # Aug 16 - Sep 15, almost none by October (Baar et al. 2008)
              measure="none", calendar_peak_doy=245.0, calendar_width_d=14.0,
              groundspeed_kmh=63.5),
    DuckGroup(key="gadwal", name="Gadwall", species=("gadwal",),
              # Notaro 2016 ~-7.7 / -7.1 / -3.9
              measure="wsimean", theta=((35.0, -7.5), (40.0, -7.0), (45.0, -5.0)),
              groundspeed_kmh=70.6),
    DuckGroup(key="amewig", name="American wigeon", species=("amewig",),
              # Notaro 2016 ~-4.6 / -10.9 / -9.1; DU press quotes ~-10
              measure="wsimean", theta=((35.0, -8.0), (40.0, -10.0), (45.0, -10.0)),
              groundspeed_kmh=52.0),
    DuckGroup(key="norpin", name="Northern pintail", species=("norpin",),
              # Notaro 2016: 7-day max WSI, zero-crossing ~-0.3 to -0.6
              measure="wsi7max", theta=((35.0, -0.5),),
              groundspeed_kmh=79.0),
)}
# which species roll up into which hunter's group
GROUP_OF = {"mallar3": "duck_mallard", "gnwtea": "duck_teal", "buwtea": "duck_teal",
            "gadwal": "duck_puddle", "amewig": "duck_puddle", "norpin": "duck_puddle"}

# O'Neal et al. 2018 (Mov. Ecol. 6:23), departure odds at a stopover:
# following wind aloft OR 35.2, no rain 13.2, not overcast 2.8; P = 0.76 when
# all favourable -> intercept logit(0.76) - ln(35.2) - ln(13.2) - ln(2.8).
NIGHT_GATE = {"or_wind": 35.2, "or_dry": 13.2, "or_clear": 2.8, "p_all": 0.76,
              "wind_full_mph": 10.0,      # tailwind counted fully favourable
              "rain_mm": 0.2, "overcast_pct": 95}
