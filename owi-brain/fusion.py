"""Fusione a pattern: co-occorrenze spazio-temporali che contano piu' dei conteggi.

strike_package : nello stesso campione, >=1 cisterna + >=3 caccia (o 1 bombardiere)
                 + 1 AWACS/ISR entro RADIUS km. E' la firma di un pacchetto d'attacco.
tanker_orbit   : cisterna che resta entro 80 km dalla stessa posizione per >=2 campioni.
isr_orbit      : piattaforma ISR in orbita persistente (stesso criterio).
"""
from collections import defaultdict

from classify import bucket
from zones import haversine_km

RADIUS = 300.0


def _samples(con, date):
    rows = con.execute(
        "SELECT ts, hex, callsign, role, nation, lat, lon, zone FROM aircraft_obs WHERE substr(ts,1,10)=?", (date,)).fetchall()
    by_ts = defaultdict(list)
    for r in rows:
        by_ts[r[0]].append(r)
    return by_ts


def strike_packages(con, date):
    found = []
    for ts, rows in _samples(con, date).items():
        tankers = [r for r in rows if bucket(r[3]) == "tanker"]
        for t in tankers:
            near = [r for r in rows if r[1] != t[1] and haversine_km(t[5], t[6], r[5], r[6]) <= RADIUS]
            fighters = [r for r in near if bucket(r[3]) == "fighter"]
            bombers = [r for r in near if bucket(r[3]) == "bomber"]
            c2 = [r for r in near if bucket(r[3]) in ("awacs", "isr")]
            if (len(fighters) >= 3 or bombers) and c2:
                found.append(dict(
                    ts=ts, zone=t[7], anchor_tanker=t[2] or t[1], lat=t[5], lon=t[6],
                    fighters=len(fighters), bombers=len(bombers), c2=[r[2] or r[1] for r in c2][:3],
                    nations=sorted({r[4] for r in [t] + near}),
                    members=[dict(hex=r[1], callsign=r[2], role=r[3]) for r in [t] + fighters + bombers + c2][:12],
                ))
    # de-duplica per cisterna: tieni il campione piu' ricco
    best = {}
    for p in found:
        k = (p["zone"], p["anchor_tanker"])
        if k not in best or p["fighters"] + 3 * p["bombers"] > best[k]["fighters"] + 3 * best[k]["bombers"]:
            best[k] = p
    return sorted(best.values(), key=lambda p: -(p["fighters"] + 3 * p["bombers"]))


def persistent_orbits(con, date, roles=("tanker", "isr", "awacs"), max_drift_km=80.0):
    track = defaultdict(list)
    for ts, rows in sorted(_samples(con, date).items()):
        for r in rows:
            if bucket(r[3]) in roles:
                track[r[1]].append(r)
    out = []
    for hx, obs in track.items():
        if len(obs) < 2:
            continue
        clat = sum(o[5] for o in obs) / len(obs)
        clon = sum(o[6] for o in obs) / len(obs)
        if all(haversine_km(clat, clon, o[5], o[6]) <= max_drift_km for o in obs):
            out.append(dict(hex=hx, callsign=obs[-1][2], role=bucket(obs[-1][3]), nation=obs[-1][4],
                            zone=obs[-1][7], lat=round(clat, 3), lon=round(clon, 3), samples=len(obs)))
    return sorted(out, key=lambda o: (o["zone"] is None, -o["samples"]))
