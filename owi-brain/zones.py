"""Teatri monitorati. Gli id coincidono con data/threat-board.json.

Ogni zona ha un centro, un raggio "core" (km) e un anello di avvicinamento
(2x raggio) dove si conta la massa in staging. Le query GDELT servono per
la velocita' delle notizie e per la ground truth (colpi entro 72h).
"""
import math

ZONES = [
    dict(id="ukraine",       name_it="Ucraina",              lat=48.5, lon=35.0,  r=650,  tz=3,
         gdelt='(airstrike OR "missile strike" OR "drone strike") (Ukraine OR Kyiv OR Kharkiv OR Odesa)'),
    dict(id="gaza",          name_it="Gaza",                 lat=31.4, lon=34.4,  r=180,  tz=3,
         gdelt='(airstrike OR strike OR shelling) (Gaza OR Rafah OR "Khan Younis")'),
    dict(id="red-sea",       name_it="Mar Rosso / Bab al-Mandeb", lat=14.5, lon=42.5, r=650, tz=3,
         gdelt='(strike OR missile OR drone OR attack) (Houthi OR "Red Sea" OR Hodeidah OR "Bab al-Mandeb")'),
    dict(id="taiwan",        name_it="Taiwan / Stretto",     lat=24.0, lon=120.5, r=450,  tz=8,
         gdelt='(PLA OR "Taiwan Strait" OR ADIZ) (drill OR incursion OR blockade OR warplanes)'),
    dict(id="korea",         name_it="Corea / DPRK",         lat=38.0, lon=127.0, r=380,  tz=9,
         gdelt='("North Korea" OR DPRK OR Pyongyang) (missile OR launch OR artillery OR drill)'),
    dict(id="sudan",         name_it="Sudan",                lat=15.5, lon=32.5,  r=550,  tz=2,
         gdelt='(Sudan OR Khartoum OR "El Fasher" OR Darfur) (airstrike OR shelling OR attack OR RSF)'),
    dict(id="lebanon-syria", name_it="Siria / Libano",       lat=34.3, lon=36.5,  r=320,  tz=3,
         gdelt='(Lebanon OR Syria OR Hezbollah OR Beirut OR Damascus) (airstrike OR strike OR "Israeli jets")'),
    dict(id="myanmar",       name_it="Myanmar",              lat=19.5, lon=96.5,  r=450,  tz=6.5,
         gdelt='(Myanmar OR Burma OR junta) (airstrike OR bombing OR attack)'),
    dict(id="sahel",         name_it="Sahel",                lat=14.0, lon=0.0,   r=900,  tz=0,
         gdelt='(Mali OR "Burkina Faso" OR Niger OR Sahel) (attack OR ambush OR airstrike OR JNIM OR ISGS)'),
    dict(id="iran-gulf",     name_it="Iran / Golfo / Hormuz", lat=27.0, lon=52.0, r=750,  tz=3.5,
         gdelt='(Iran OR Hormuz OR IRGC OR "Persian Gulf") (strike OR attack OR missile OR tanker)'),
    dict(id="nato-baltic",   name_it="NATO / Baltico",       lat=58.0, lon=24.0,  r=550,  tz=2,
         gdelt='(Baltic OR Kaliningrad OR Estonia OR Latvia OR Lithuania OR Suwalki) (Russia) (incursion OR jets OR drone OR sabotage)'),
    dict(id="arctic",        name_it="Artico",               lat=75.0, lon=40.0,  r=1300, tz=3,
         gdelt='(Arctic OR Svalbard OR Barents OR "Kola Peninsula") (Russia OR NATO) (bomber OR submarine OR exercise)'),
]
ZONE_BY_ID = {z["id"]: z for z in ZONES}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def locate(lat, lon):
    """Ritorna (zone_id, ring) con ring 'core' | 'approach' | None.
    Se un punto cade in piu' zone vince la piu' vicina in unita' di raggio."""
    best = None
    for z in ZONES:
        d = haversine_km(lat, lon, z["lat"], z["lon"])
        u = d / z["r"]
        if u <= 2.0 and (best is None or u < best[2]):
            best = (z["id"], "core" if u <= 1.0 else "approach", u)
    return (best[0], best[1]) if best else (None, None)
