"""Feature per zona e per giorno, calcolate dalla cache SQLite.

Conteggi = velivoli DISTINTI (hex) visti nel giorno nel core della zona,
piu' la massa in staging (anello di avvicinamento). Con piu' campioni per run
il conteggio distinto e' piu' stabile della media per campione.
"""
import json
import math
from collections import defaultdict

from classify import bucket
from zones import ZONES, ZONE_BY_ID

BUCKETS = ["fighter", "bomber", "tanker", "awacs", "isr", "transport", "helicopter"]


def daily_features(con, date):
    """Ritorna {zone_id: {feature: valore}} per la data (YYYY-MM-DD)."""
    feats = {z["id"]: defaultdict(float) for z in ZONES}
    hex_sets = {z["id"]: defaultdict(set) for z in ZONES}
    nations = {z["id"]: set() for z in ZONES}
    night = {z["id"]: [0, 0] for z in ZONES}
    rows = con.execute(
        "SELECT hex, role, nation, zone, ring, ts, lat, lon FROM aircraft_obs WHERE zone IS NOT NULL AND substr(ts,1,10)=?",
        (date,)).fetchall()
    for hx, role, nation, zone, ring, ts, lat, lon in rows:
        b = bucket(role)
        key = b if ring == "core" else f"approach_{b}"
        hex_sets[zone][key].add(hx)
        hex_sets[zone]["all" if ring == "core" else "approach_all"].add(hx)
        if ring == "core":
            nations[zone].add(nation)
            hour_local = (int(ts[11:13]) + ZONE_BY_ID[zone]["tz"]) % 24
            night[zone][1] += 1
            if hour_local < 5 or hour_local >= 22:
                night[zone][0] += 1
    for zid in feats:
        for k, s in hex_sets[zid].items():
            feats[zid][k] = float(len(s))
        for b in BUCKETS:
            feats[zid].setdefault(b, 0.0)
            feats[zid].setdefault(f"approach_{b}", 0.0)
        feats[zid].setdefault("all", 0.0)
        feats[zid].setdefault("approach_all", 0.0)
        feats[zid]["n_nations"] = float(len(nations[zid]))
        feats[zid]["night_share"] = night[zid][0] / night[zid][1] if night[zid][1] else 0.0
        feats[zid]["_nations"] = sorted(nations[zid])
    # GDELT: volume del giorno (media se ci sono piu' fetch)
    for zid, v in con.execute(
            "SELECT zone, AVG(vol_strike) FROM gdelt_daily WHERE date=? GROUP BY zone", (date,)).fetchall():
        if zid in feats:
            feats[zid]["news_strike_vol"] = float(v or 0)
    for zid in feats:
        feats[zid].setdefault("news_strike_vol", 0.0)
    # threat-board: ultimo punteggio disponibile fino a quel giorno e delta rispetto al precedente
    for zid in feats:
        pts = con.execute(
            "SELECT score FROM threat_scores WHERE zone=? AND substr(fetched_at,1,10)<=? ORDER BY fetched_at DESC LIMIT 2",
            (zid, date)).fetchall()
        feats[zid]["threat_score"] = float(pts[0][0]) if pts else 0.0
        feats[zid]["threat_delta"] = float(pts[0][0] - pts[1][0]) if len(pts) == 2 else 0.0
    return {z: dict(f) for z, f in feats.items()}


def observed_dates(con):
    return [r[0] for r in con.execute("SELECT DISTINCT substr(ts,1,10) FROM aircraft_obs ORDER BY 1").fetchall()]


def baseline(history, feature, exclude_date=None, min_days=5):
    """history: lista di (date, feats_zone). Ritorna (mean, std, n)."""
    xs = [f.get(feature, 0.0) for d, f in history if d != exclude_date]
    n = len(xs)
    if n < min_days:
        return None, None, n
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / max(n - 1, 1)
    return m, math.sqrt(var), n


def zscore(x, mean, std):
    if mean is None:
        return 0.0
    floor = max(0.5, math.sqrt(max(mean, 0.0)))  # rumore di Poisson su conteggi piccoli
    return (x - mean) / max(std or 0.0, floor)
