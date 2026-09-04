"""Feed live dei velivoli militari, pensato per girare ogni 10 minuti su GitHub Actions.

Fonti (adsb.lol, nessuna chiave):
  /v2/mil                 velivoli con flag militare nel database
  /v2/point/lat/lon/250   tutto il traffico entro 250 NM dai teatri: qui si pescano i militari
                          che il database non marca (Russia, Cina, Iran...) con hex, callsign,
                          matricola e tipo.
Output:
  <out>/aircraft-live.json      per la dashboard (formato gia' pronto per trackedAircraft)
  <samples>/YYYY-MM-DD.jsonl.gz campioni per la memoria del brain (schema aircraft_obs)

Uso: python live.py [--out DIR] [--samples DIR]
"""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify  # noqa: E402
from zones import locate  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) OWI-live/1.0 (+https://openwarintelligence.org)"}
BASE = "https://api.adsb.lol/v2"

# Punti di osservazione: (nome, lat, lon). Raggio 250 NM = il massimo dell'API.
HOTSPOTS = [
    ("Baltico", 57.0, 21.0), ("Mare del Nord", 55.5, 4.0), ("Polonia/Germania", 51.5, 16.0),
    ("Ucraina ovest", 49.0, 27.0), ("Mar Nero", 45.0, 33.0), ("Romania/Bulgaria", 44.5, 27.0),
    ("Med. orientale", 34.5, 32.0), ("Siria/Iraq", 35.0, 39.0), ("Golfo", 26.0, 52.0),
    ("Mar Rosso", 16.0, 42.0), ("Corno d'Africa", 12.0, 45.0),
    ("Taiwan", 24.5, 121.0), ("Corea", 37.0, 127.5), ("Giappone", 35.0, 137.0), ("Okinawa", 26.5, 128.0),
    ("Kola/Artico", 69.0, 33.0), ("Alaska", 61.5, -150.0), ("Guam", 14.0, 145.0),
    ("Sahel", 15.0, 2.0), ("Sudan", 15.5, 32.5), ("Myanmar", 19.5, 96.5),
]

# Tipi ICAO inequivocabilmente militari: bastano da soli a marcare il velivolo.
MIL_TYPES = {
    "K35R", "K35E", "KC46", "KC10", "IL78", "E3TF", "E3CF", "E7", "E737", "A50", "KJ50", "E2", "E2C", "E2D", "E6", "E4",
    "RC135", "R135", "P8", "P3", "P3C", "Q4", "RQ4", "MQ9", "MQ4", "U2", "E8", "EP3", "IL20", "IL38",
    "F16", "F15", "F18", "F18S", "FA18", "F22", "F35", "EUFI", "TYPH", "RFAL", "TORD", "JAS39", "GRIP", "M2000", "MIR2",
    "SU27", "SU30", "SU35", "SU57", "MG29", "MG31", "J10", "J11", "J16", "J20", "F2", "F4", "F5", "A10", "SU25",
    "HAR", "AV8B", "T50", "KF21", "TEJA", "F14", "B1", "B2", "B52", "SU24", "SU34", "TU95", "TU16", "TU22", "H6", "JH7",
    "C17", "C5M", "C5", "C130", "C30J", "A400", "C27J", "AN12", "AN26", "AN72", "AN124", "A124", "Y20", "C2", "C160", "KC39",
    "H60", "UH60", "H64", "AH64", "H47", "CH47", "V22", "NH90", "EH10", "MI8", "MI17", "MI24", "MI28", "KA52", "H53", "MH60", "TIGR",
    "T6", "T38", "PC21", "M346", "T7", "T45", "L39", "AJET", "M339", "TEX2", "HAWK",
}
MIL_HEX = [  # blocchi militari noti (conservativi)
    (0xADF7C8, 0xAFFFFF, "USA"), (0x43C000, 0x43CFFF, "UK"), (0x3F4000, 0x3FFFFF, "DEU"), (0x3B7000, 0x3B7FFF, "FRA"),
    (0x33FF00, 0x33FFFF, "ITA"), (0x480000, 0x4807FF, "NLD"), (0x738A00, 0x738AFF, "ISR"),
]
# NB: niente UAE (Emirates), SVA (Saudia), EJA (NetJets): compagnie civili con lo stesso prefisso.
CALLSIGN_PREFIXES = tuple(p for p, _ in classify.CALLSIGN_ROLE) + (
    "RRR", "NATO", "IAM", "GAF", "FAF", "CTM", "THK", "TUAF", "HAF", "PLF", "SVF", "NAF", "DAF", "FIF", "IASF", "IAF",
    "JASDF", "ROKAF", "RAAF", "CFC", "IFC", "RSAF", "EAF", "PAF", "BAF", "ROF", "CEF", "HUF", "AME", "MMI", "FNY",
    "LOSSIE", "TRSTN", "DCH", "KAF", "ASY", "RNL", "NORW", "RCH", "REACH", "CNV", "VVLL", "VMLL",
)
BUCKET_TO_DASH = {"fighter": "fighter", "bomber": "bomber", "tanker": "tanker", "transport": "transport",
                  "helicopter": "helicopter", "awacs": "recon", "isr": "recon", "other": "transport"}
LABELS = {
    "K35R": "KC-135R Stratotanker", "KC46": "KC-46 Pegasus", "KC10": "KC-10 Extender", "A332": "A330 MRTT", "IL78": "Il-78 Midas",
    "E3TF": "E-3 Sentry AWACS", "E3CF": "E-3F AWACS", "E7": "E-7 Wedgetail", "A50": "A-50 Mainstay", "E2D": "E-2D Hawkeye",
    "E6": "E-6B Mercury", "E4": "E-4B Nightwatch", "RC135": "RC-135 Rivet Joint", "P8": "P-8A Poseidon", "P3": "P-3 Orion",
    "Q4": "RQ-4 Global Hawk", "MQ9": "MQ-9 Reaper", "MQ4": "MQ-4C Triton", "U2": "U-2 Dragon Lady", "E8": "E-8 JSTARS",
    "CL60": "CL-650 Artemis/ISR", "GLF5": "G-V ISR", "G550": "G550 CAEW/ISR", "B350": "King Air ISR", "BE20": "King Air",
    "F16": "F-16 Fighting Falcon", "F15": "F-15 Eagle", "F18": "F/A-18 Hornet", "F18S": "F/A-18E Super Hornet", "F22": "F-22 Raptor",
    "F35": "F-35 Lightning II", "EUFI": "Eurofighter Typhoon", "RFAL": "Rafale", "TORD": "Tornado", "JAS39": "JAS 39 Gripen",
    "M2000": "Mirage 2000", "SU27": "Su-27 Flanker", "SU30": "Su-30", "SU35": "Su-35", "SU57": "Su-57 Felon", "MG29": "MiG-29",
    "MG31": "MiG-31", "J10": "J-10", "J16": "J-16", "J20": "J-20", "A10": "A-10 Thunderbolt II", "F2": "Mitsubishi F-2",
    "B1": "B-1B Lancer", "B2": "B-2 Spirit", "B52": "B-52H Stratofortress", "SU34": "Su-34 Fullback", "SU24": "Su-24 Fencer",
    "TU95": "Tu-95 Bear", "TU22": "Tu-22M Backfire", "TU160": "Tu-160 Blackjack", "H6": "H-6 Badger",
    "C17": "C-17 Globemaster III", "C5M": "C-5M Super Galaxy", "C130": "C-130 Hercules", "C30J": "C-130J Super Hercules",
    "A400": "A400M Atlas", "C27J": "C-27J Spartan", "C295": "C-295", "IL76": "Il-76 Candid", "AN124": "An-124 Ruslan",
    "AN26": "An-26", "AN12": "An-12", "Y20": "Y-20 Kunpeng", "C2": "Kawasaki C-2", "C40": "C-40 Clipper", "C32": "C-32",
    "C37": "C-37 (Gulfstream)", "B737": "B737 (governativo)", "B752": "C-32/B757", "KC39": "KC-390", "C160": "C-160 Transall",
    "H60": "UH/HH-60 Black Hawk", "H64": "AH-64 Apache", "H47": "CH-47 Chinook", "V22": "V-22 Osprey", "NH90": "NH90",
    "EH10": "AW101 Merlin", "MI8": "Mi-8/17 Hip", "MI24": "Mi-24 Hind", "MI28": "Mi-28", "KA52": "Ka-52", "H53": "CH-53",
    "T6": "T-6 Texan II", "T38": "T-38 Talon", "PC21": "PC-21", "M346": "M-346", "HAWK": "Hawk", "PC12": "PC-12 ISR",
}


def http_json(url, timeout=30, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace").strip()
                return json.loads(raw) if raw else None
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    print(f"  [warn] {url[:70]} -> {last}", file=sys.stderr)
    return None


def is_military(a):
    """Ritorna (bool, motivo)."""
    if (a.get("dbFlags") or 0) & 1:
        return True, "db"
    t = (a.get("t") or "").upper()
    if t in MIL_TYPES:
        return True, "type"
    cs = (a.get("flight") or "").strip().upper()
    if cs and cs.startswith(CALLSIGN_PREFIXES):
        return True, "callsign"
    reg = (a.get("r") or "").upper()
    if reg.startswith("RF-") or (reg.startswith("RA-") and t in ("IL76", "AN12", "AN26", "AN72", "AN124")):
        return True, "reg"
    try:
        h = int(a.get("hex") or "", 16)
        for lo, hi, _ in MIL_HEX:
            if lo <= h <= hi:
                return True, "hex"
    except ValueError:
        pass
    return False, ""


def nation_of(a):
    n = classify.nation_of(a.get("hex"))
    reg = (a.get("r") or "").upper()
    if reg.startswith("RF-") or reg.startswith("RA-"):
        return "RUS"
    return n


def to_row(a, src, ts, run_id):
    role = classify.role_of(a.get("t"), a.get("flight"))
    b = classify.bucket(role)
    alt = a.get("alt_baro")
    alt = 0 if alt in (None, "ground") else alt
    lat, lon = a["lat"], a["lon"]
    zone, ring = locate(lat, lon)
    t = (a.get("t") or "").upper()
    return dict(
        ts=ts, run_id=run_id, hex=(a.get("hex") or "").lower(), callsign=(a.get("flight") or "").strip(),
        reg=a.get("r") or "", type_code=t, role=role, nation=nation_of(a), lat=round(lat, 4), lon=round(lon, 4),
        alt=int(alt or 0), gs=round(a.get("gs") or 0, 1), track=round(a.get("track") or 0, 1),
        squawk=a.get("squawk") or "", zone=zone, ring=ring, src=src, dash_type=BUCKET_TO_DASH.get(b, "transport"),
        label=LABELS.get(t, t or "Military"),
    )


def collect():
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    found, stats = {}, {"mil_feed": 0, "hotspots": 0, "by_reason": {}}
    d = http_json(f"{BASE}/mil")
    for a in (d or {}).get("ac", []) or []:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        found[a["hex"].lower()] = to_row(a, "adsb.lol/mil", ts, run_id)
        stats["mil_feed"] += 1
    for name, lat, lon in HOTSPOTS:
        d = http_json(f"{BASE}/point/{lat}/{lon}/250")
        n = 0
        for a in (d or {}).get("ac", []) or []:
            if a.get("lat") is None or a.get("lon") is None or a.get("alt_baro") == "ground":
                continue
            hx = (a.get("hex") or "").lower()
            if hx in found:
                continue
            ok, why = is_military(a)
            if ok:
                found[hx] = to_row(a, f"adsb.lol/{name}", ts, run_id)
                stats["by_reason"][why] = stats["by_reason"].get(why, 0) + 1
                n += 1
        stats["hotspots"] += n
        time.sleep(0.4)
    return run_id, ts, list(found.values()), stats


def main():
    out_dir = "out"
    samples_dir = "samples"
    args = sys.argv[1:]
    if "--out" in args:
        out_dir = args[args.index("--out") + 1]
    if "--samples" in args:
        samples_dir = args[args.index("--samples") + 1]
    run_id, ts, rows, stats = collect()
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(samples_dir, exist_ok=True)
    dash = [dict(icao=r["hex"], call=r["callsign"] or r["hex"].upper(), lat=r["lat"], lng=r["lon"], alt=r["alt"],
                 spd=r["gs"], heading=r["track"], type=r["dash_type"], label=r["label"], nation=r["nation"],
                 model=r["type_code"], reg=r["reg"], source="owi-live", zone=r["zone"]) for r in rows]
    nations = {}
    for r in rows:
        nations[r["nation"]] = nations.get(r["nation"], 0) + 1
    json.dump(dict(schema="owi-live/1", generated_at=ts, count=len(dash), stats=stats, nations=nations, ac=dash),
              open(os.path.join(out_dir, "aircraft-live.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    # campioni per la memoria: solo i campi dello schema aircraft_obs
    keep = ("ts", "run_id", "hex", "callsign", "reg", "type_code", "role", "nation", "lat", "lon", "alt", "gs", "track", "squawk", "zone", "ring")
    day = ts[:10]
    with gzip.open(os.path.join(samples_dir, f"{day}.jsonl.gz"), "at", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in keep}, separators=(",", ":")) + "\n")
    # tieni solo gli ultimi 3 giorni di campioni sul branch live
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    for fn in os.listdir(samples_dir):
        if fn.endswith(".jsonl.gz") and fn[:10] < cutoff:
            os.remove(os.path.join(samples_dir, fn))
    print(f"[live] {len(dash)} velivoli militari (feed {stats['mil_feed']}, hotspot +{stats['hotspots']} {stats['by_reason']}); "
          f"nazioni: {dict(sorted(nations.items(), key=lambda x: -x[1])[:8])}")


if __name__ == "__main__":
    main()
