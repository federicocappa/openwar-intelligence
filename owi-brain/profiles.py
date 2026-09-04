"""Profilo per singolo mezzo (hex ICAO) e anomalie individuali.

Per ogni cellula vista abbastanza volte: base di casa (base militare piu'
vicina alle posizioni a bassa quota o al baricentro), teatro abituale,
orari abituali, giorni della settimana. Un mezzo che oggi sta in un teatro
dove non e' mai stato, o in orario inconsueto, e' un'anomalia individuale.
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

from zones import haversine_km

ROOT = os.path.dirname(os.path.abspath(__file__))
BASES = json.load(open(os.path.join(ROOT, "bases.json"), encoding="utf-8"))
MIN_OBS = 6
MIN_DAYS = 3


def nearest_base(lat, lon):
    best, bd = None, 1e9
    for b in BASES:
        d = haversine_km(lat, lon, b["lat"], b["lon"])
        if d < bd:
            best, bd = b, d
    return (best["name"] if bd <= 250 else None), round(bd)


def build_profiles(con, until_date):
    rows = con.execute(
        "SELECT hex, callsign, reg, type_code, role, nation, lat, lon, alt, zone, ts FROM aircraft_obs "
        "WHERE substr(ts,1,10)<? ORDER BY ts", (until_date,)).fetchall()
    by_hex = defaultdict(list)
    for r in rows:
        by_hex[r[0]].append(r)
    profiles = {}
    for hx, obs in by_hex.items():
        days = {o[10][:10] for o in obs}
        if len(obs) < MIN_OBS or len(days) < MIN_DAYS:
            continue
        zones = Counter(o[9] for o in obs if o[9])
        hours = Counter(int(o[10][11:13]) for o in obs)
        dows = Counter(datetime.strptime(o[10][:10], "%Y-%m-%d").weekday() for o in obs)
        low = [o for o in obs if o[8] and o[8] < 8000] or obs
        clat = sum(o[6] for o in low) / len(low)
        clon = sum(o[7] for o in low) / len(low)
        home, dist = nearest_base(clat, clon)
        calls = Counter(o[1] for o in obs if o[1])
        profiles[hx] = dict(
            hex=hx, reg=next((o[2] for o in reversed(obs) if o[2]), ""), type_code=obs[-1][3], role=obs[-1][4],
            nation=obs[-1][5], n_obs=len(obs), n_days=len(days), first_seen=obs[0][10][:10], last_seen=obs[-1][10][:10],
            home_base=home, home_dist_km=dist, usual_callsigns=[c for c, _ in calls.most_common(3)],
            zones={z: round(n / len(obs), 2) for z, n in zones.most_common(4)},
            hours={str(h): n for h, n in sorted(hours.items())}, dows={str(d): n for d, n in sorted(dows.items())},
        )
    return profiles


def individual_anomalies(con, date, profiles):
    """Mezzi noti che oggi sono fuori dal loro schema."""
    rows = con.execute(
        "SELECT hex, callsign, type_code, role, nation, zone, ts, lat, lon FROM aircraft_obs "
        "WHERE substr(ts,1,10)=? AND zone IS NOT NULL", (date,)).fetchall()
    seen = {}
    for hx, cs, tc, role, nat, zone, ts, lat, lon in rows:
        seen.setdefault(hx, (cs, tc, role, nat, zone, ts, lat, lon))
    out = []
    for hx, (cs, tc, role, nat, zone, ts, lat, lon) in seen.items():
        p = profiles.get(hx)
        if not p:
            continue
        reasons = []
        if zone not in p["zones"]:
            reasons.append(f"mai visto in {zone} (abituale: {', '.join(p['zones']) or 'nessun teatro'})")
        h = int(ts[11:13])
        tot = sum(p["hours"].values())
        near = sum(p["hours"].get(str((h + d) % 24), 0) for d in (-1, 0, 1))
        if tot >= 10 and near / tot < 0.05:
            reasons.append(f"orario inconsueto ({h:02d}Z, {near}/{tot} osservazioni storiche)")
        if reasons:
            out.append(dict(hex=hx, callsign=cs, type_code=tc, role=role, nation=nat, zone=zone, lat=lat, lon=lon,
                            home_base=p["home_base"], n_days=p["n_days"], reasons_it=reasons))
    out.sort(key=lambda a: (-len(a["reasons_it"]), -a["n_days"]))
    return out[:40]
