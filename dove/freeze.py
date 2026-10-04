"""Freeze and snow: what drives ducks off their water (D26).

Weather Severity Index, Schummer et al. 2010, J. Wildl. Manage. 74:94-101,
Table 2, computed where the birds are LEAVING:

    WSI = TEMP + TEMPDAYS + SNOW + SNOWDAYS
      TEMP      = -(daily mean temperature, deg C)
      TEMPDAYS  = consecutive days with mean temperature <= 0 C
      SNOW      = snow depth in inches (cm x 0.394, whole inches as in the
                  paper's examples: 3 cm -> 1, 26 cm -> 10)
      SNOWDAYS  = consecutive days with >= 2.54 cm of snow on the ground

Paper's worked example - mean temps 2, -1, -5 C with snow 0, 3, 26 cm ->
WSI -2, 4, 19 - is a unit test (verify_worked_example).

Also, from Notaro et al. 2016 (PLoS ONE e0167506), the variants their
species models use: WSIMEAN (the 7-day mean temperature in TEMP) and the
7-day maximum WSI (pintail). And a wetland-ice proxy from Weller et al. 2022
(Mov. Ecol. 10:1): ice forms after 2 days with mean < 0 C, grows 1 cm per
3.3 freezing degree-days and melts 1 cm per 1.3 thawing degree-days.
"""


def wsi_series(feats):
    """{date: daily features} -> {date: {wsi, wsimean, wsi7max, tempdays,
    snowdays, ice_cm}}. Days without tmean_c are skipped and break the runs
    (the counts are of CONSECUTIVE days we actually have)."""
    out, tempdays, snowdays, cold_run, ice = {}, 0, 0, 0, 0.0
    window, wsis, prev = [], [], None
    for d in sorted(feats):
        f = feats[d]
        t = f.get("tmean_c")
        if t is None:
            tempdays = snowdays = cold_run = 0
            window, wsis = [], []
            continue
        snow = f.get("snow_cm", 0.0) or 0.0
        tempdays = tempdays + 1 if t <= 0 else 0
        snowdays = snowdays + 1 if snow >= 2.54 else 0
        inches = round(snow * 0.394)
        wsi = -t + tempdays + inches + snowdays
        window = (window + [t])[-7:]
        wsimean = -(sum(window) / len(window)) + tempdays + inches + snowdays
        wsis = (wsis + [wsi])[-7:]
        cold_run = cold_run + 1 if t < 0 else 0
        if cold_run >= 2 or ice > 0:
            ice = max(0.0, ice + (-t / 3.3 if t < 0 else -t / 1.3))
        out[d] = {"wsi": round(wsi, 2), "wsimean": round(wsimean, 2),
                  "wsi7max": round(max(wsis), 2), "tempdays": tempdays,
                  "snowdays": snowdays, "ice_cm": round(ice, 1)}
    return out


def verify_worked_example():
    feats = {"2010-01-01": {"tmean_c": 2, "snow_cm": 0},
             "2010-01-02": {"tmean_c": -1, "snow_cm": 3},
             "2010-01-03": {"tmean_c": -5, "snow_cm": 26}}
    got = [v["wsi"] for _, v in sorted(wsi_series(feats).items())]
    assert got == [-2, 4, 19], got
    return got
