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
    arrival_hour: int = 8
    season_start: tuple = (8, 15)        # (month, day) the reservoir replay starts
    reservoir_k: float = 0.25
    bands: tuple = tuple(BANDS)
    gate: object = field(default=photoperiod_gate, compare=False, repr=False)


DOVE = Profile(key="dove", name="Mourning dove", species=("moudov",))

PROFILES = {p.key: p for p in (DOVE,)}
