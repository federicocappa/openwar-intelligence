"""Fonti ausiliarie lette dal brain (ogni ora, dentro il job live) e servite come file statici.

  firms.json  NASA FIRMS VIIRS (Suomi NPP) 24h: hotspot termici entro 888 km dai teatri.
              Nessuna chiave: CSV pubblico. Il browser non lo raggiunge (CORS): lo legge il brain.
  news.json   19 feed RSS (mainstream + OSINT difesa), filtrati per parole chiave militari,
              con data ISO, fonte, teatro stimato. Sostituisce rss2json (bloccato dalla CSP).
  satellites.json  TLE reali da CelesTrak (GP) per ~250 piattaforme militari/dual-use (ISR, SAR, SIGINT,
              early warning, comms). La dashboard propaga con SGP4 (satellite.js). I satelliti NRO
              classificati NON hanno TLE pubblici: non compaiono, e lo diciamo.
  fleet.json  USNI News Fleet & Marine Tracker (settimanale): gruppi navali USA dispiegati, con REGIONE
              (non coordinate) e data "as of". Posizione = centroide della regione, dichiarata approssimata.
  ais-mil.json  AIS via aisstream.io (websocket, chiave in AISSTREAM_KEY): navi con tipo 35 (military ops)
              o nome navale. Senza chiave il file non viene scritto.

Regola: se una fonte non risponde, il file NON viene scritto e la dashboard mostra
"non disponibile". Mai dati di ripiego.

Uso: python aux.py --out DIR
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zones import ZONES, haversine_km  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) OWI-brain/1.0 (+https://openwarintelligence.org)"}
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv"
FIRMS_RADIUS_KM = 888
FIRMS_MAX = 2500

RSS_FEEDS = [
    ("Reuters World", "https://feeds.reuters.com/Reuters/worldNews", "NEWS"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "NEWS"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "NEWS"),
    ("Guardian World", "https://www.theguardian.com/world/rss", "NEWS"),
    ("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/", "OSINT"),
    ("Military Times", "https://www.militarytimes.com/arc/outboundfeeds/rss/", "OSINT"),
    ("Janes Defence", "https://www.janes.com/feeds/news", "OSINT"),
    ("Breaking Defense", "https://breakingdefense.com/feed/", "OSINT"),
    ("War on the Rocks", "https://warontherocks.com/feed/", "OSINT"),
    ("The War Zone", "https://www.thedrive.com/the-war-zone/feed", "OSINT"),
    ("IISS", "https://www.iiss.org/rss", "OSINT"),
    ("ISW", "https://understandingwar.org/feed", "OSINT"),
    ("Arms Control", "https://www.armscontrol.org/rss.xml", "OSINT"),
    ("Bulletin Atomic", "https://thebulletin.org/feed/", "OSINT"),
    ("SIPRI", "https://www.sipri.org/rss.xml", "OSINT"),
    ("Liveuamap", "https://liveuamap.com/rss", "OSINT"),
    ("Oryx OSINT", "https://www.oryxspioenkop.com/feeds/posts/default?alt=rss", "OSINT"),
    ("CriticalThreats", "https://www.criticalthreats.org/rss.xml", "OSINT"),
    ("Long War Journal", "https://www.longwarjournal.org/feed", "OSINT"),
]
MIL_KEYWORDS = ("military", "war", "conflict", "nato", "army", "navy", "missile", "drone", "bomb", "strike", "troops",
                "tank", "defense", "defence", "ukraine", "gaza", "israel", "russia", "china", "taiwan", "nuclear",
                "iran", "houthi", "hezbollah", "korea", "sudan", "sahel", "airstrike", "artillery", "submarine", "warship",
                "ceasefire", "offensive", "escalation", "sanction", "pentagon", "kremlin", "idf", "pla ")
ZONE_KEYWORDS = {
    "ukraine": ("ukrain", "kyiv", "kharkiv", "odesa", "donetsk", "zaporizh", "crimea", "kursk"),
    "gaza": ("gaza", "rafah", "hamas", "khan younis", "west bank"),
    "red-sea": ("houthi", "red sea", "hodeidah", "bab al-mandeb", "bab el-mandeb", "yemen"),
    "taiwan": ("taiwan", "taipei", "pla ", "strait"),
    "korea": ("north korea", "pyongyang", "dprk", "kim jong"),
    "sudan": ("sudan", "khartoum", "darfur", "el fasher", "rsf"),
    "lebanon-syria": ("lebanon", "hezbollah", "beirut", "syria", "damascus"),
    "myanmar": ("myanmar", "burma", "junta"),
    "sahel": ("mali", "burkina", "niger", "sahel", "jnim"),
    "iran-gulf": ("iran", "tehran", "hormuz", "irgc", "persian gulf", "tanker"),
    "nato-baltic": ("baltic", "kaliningrad", "estonia", "latvia", "lithuania", "poland", "suwalki", "finland"),
    "arctic": ("arctic", "svalbard", "barents", "kola", "greenland"),
}


def fetch(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def build_firms():
    raw = fetch(FIRMS_URL, timeout=180).decode("utf-8", "replace")
    rd = csv.DictReader(io.StringIO(raw))
    pts = []
    for row in rd:
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            continue
        zone = None
        for z in ZONES:
            if haversine_km(lat, lon, z["lat"], z["lon"]) < FIRMS_RADIUS_KM:
                zone = z["id"]
                break
        if not zone:
            continue
        try:
            frp = float(row.get("frp") or 0)
        except ValueError:
            frp = 0.0
        conf = row.get("confidence", "")
        pts.append(dict(lat=round(lat, 3), lng=round(lon, 3), frp=round(frp, 1), confidence=conf,
                        date=row.get("acq_date", ""), time=row.get("acq_time", ""), daynight=row.get("daynight", ""), zone=zone))
    pts.sort(key=lambda p: -p["frp"])
    total = len(pts)
    pts = pts[:FIRMS_MAX]
    by_zone = {}
    for p in pts:
        by_zone[p["zone"]] = by_zone.get(p["zone"], 0) + 1
    return dict(schema="owi-firms/1", generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source="NASA FIRMS VIIRS Suomi NPP 24h", radius_km=FIRMS_RADIUS_KM, total_in_theatres=total,
                shown=len(pts), by_zone=by_zone, hotspots=pts)


def _text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return re.sub(r"<[^>]+>", "", x.text).strip()
    return ""


def _date(el):
    for n in ("pubDate", "{http://purl.org/dc/elements/1.1/}date", "published", "updated"):
        x = el.find(n)
        if x is not None and x.text:
            t = x.text.strip()
            try:
                return parsedate_to_datetime(t).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:  # noqa: BLE001
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:  # noqa: BLE001
                    return t[:25]
    return ""


def build_news():
    items, status = [], {}
    atom = "{http://www.w3.org/2005/Atom}"
    for name, url, tag in RSS_FEEDS:
        try:
            root = ET.fromstring(fetch(url, timeout=30))
            entries = root.findall(".//item") or root.findall(f".//{atom}entry")
            n = 0
            for e in entries[:40]:
                title = _text(e, "title", f"{atom}title")
                link = _text(e, "link") or (e.find(f"{atom}link").get("href") if e.find(f"{atom}link") is not None else "")
                desc = _text(e, "description", "summary", f"{atom}summary", f"{atom}content")[:300]
                blob = (title + " " + desc).lower()
                if tag == "NEWS" and not any(k in blob for k in MIL_KEYWORDS):
                    continue
                zone = next((z for z, kws in ZONE_KEYWORDS.items() if any(k in blob for k in kws)), None)
                items.append(dict(title=title[:220], link=link, source=name, tag=tag, published=_date(e), zone=zone, summary=desc[:200]))
                n += 1
            status[name] = n
        except Exception as e:  # noqa: BLE001
            status[name] = f"errore: {type(e).__name__}"
        time.sleep(0.5)
    seen, uniq = set(), []
    for it in sorted(items, key=lambda i: i["published"], reverse=True):
        k = it["title"].lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    return dict(schema="owi-news/1", generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                feeds=status, count=len(uniq[:200]), items=uniq[:200])


# ---------------------------------------------------------------------------
# SATELLITI — TLE reali (CelesTrak GP). (query, categoria, nazione, ruolo)
# ---------------------------------------------------------------------------
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?{q}&FORMAT=tle"
SAT_QUERIES = [
    ("NAME=SBIRS", "EW", "USA", "early warning IR"),
    ("NAME=DSP", "EW", "USA", "early warning IR"),
    ("NAME=WGS", "COMMS", "USA", "comms militari"),
    ("NAME=AEHF", "COMMS", "USA", "comms protette"),
    ("NAME=MUOS", "COMMS", "USA", "comms navali"),
    ("NAME=SBSS", "SSA", "USA", "sorveglianza spaziale"),
    ("NAME=GSSAP", "SSA", "USA", "sorveglianza GEO"),
    ("NAME=SKYNET", "COMMS", "GBR", "comms militari"),
    ("NAME=SYRACUSE", "COMMS", "FRA", "comms militari"),
    ("NAME=CSO", "ISR", "FRA", "ottico militare"),
    ("NAME=HELIOS", "ISR", "FRA", "ottico militare"),
    ("NAME=PLEIADES", "ISR", "FRA", "ottico dual-use"),
    ("NAME=SAR-LUPE", "SAR", "DEU", "radar militare"),
    ("NAME=SARAH", "SAR", "DEU", "radar militare"),
    ("NAME=TERRASAR", "SAR", "DEU", "radar dual-use"),
    ("NAME=TANDEM", "SAR", "DEU", "radar dual-use"),
    ("NAME=COSMO", "SAR", "ITA", "radar dual-use"),
    ("NAME=OPTSAT", "ISR", "ITA", "ottico militare"),
    ("NAME=SENTINEL-1", "SAR", "EU", "radar Copernicus"),
    ("NAME=ICEYE", "SAR", "FIN", "radar commerciale (uso UKR)"),
    ("NAME=CAPELLA", "SAR", "USA", "radar commerciale"),
    ("NAME=OFEK", "ISR", "ISR", "ottico/radar militare"),
    ("NAME=OFEQ", "ISR", "ISR", "ottico/radar militare"),
    ("NAME=YAOGAN", "ISR", "CHN", "ISR/ELINT militare"),
    ("NAME=GAOFEN", "ISR", "CHN", "ottico/radar dual-use"),
    ("NAME=TJS", "SIGINT", "CHN", "SIGINT/EW GEO"),
    ("NAME=SHIJIAN", "SSA", "CHN", "sperimentale/SSA"),
    ("NAME=LOTOS", "SIGINT", "RUS", "ELINT Liana"),
    ("NAME=PION", "SIGINT", "RUS", "ELINT navale"),
    ("NAME=BARS", "ISR", "RUS", "cartografico militare"),
    ("NAME=KONDOR", "SAR", "RUS", "radar militare"),
    ("NAME=PERSONA", "ISR", "RUS", "ottico militare"),
    ("NAME=KOMPSAT", "ISR", "KOR", "ottico/radar dual-use"),
    ("NAME=GOKTURK", "ISR", "TUR", "ottico militare"),
    ("NAME=CARTOSAT", "ISR", "IND", "ottico dual-use"),
    ("NAME=RISAT", "SAR", "IND", "radar militare"),
    ("NAME=EMISAT", "SIGINT", "IND", "ELINT"),
    ("GROUP=military", "MIL", None, "vario"),  # per ultimo: le query specifiche hanno la precedenza
]
SAT_MAX = 400


def build_satellites():
    seen, sats, errors = set(), [], []
    for q, cat, nation, role in SAT_QUERIES:
        try:
            txt = fetch(CELESTRAK.format(q=q), timeout=40).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{q}: {type(e).__name__}")
            continue
        lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
        for i in range(0, len(lines) - 2, 3):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            if not (l1.startswith("1 ") and l2.startswith("2 ")):
                continue
            norad = l1[2:7].strip()
            if norad in seen:
                continue
            seen.add(norad)
            nat = nation
            if nat is None:
                nat = "USA" if ("PRAETORIAN" in name or "VICTUS" in name or "USA " in name) else ("CAN" if "SAPPHIRE" in name else ("DEU" if "SAR-LUPE" in name else "UNK"))
            try:
                mm = float(l2[52:63])
                period_min = round(1440.0 / mm, 1) if mm else None
                inc = float(l2[8:16])
            except ValueError:
                period_min, inc = None, None
            # GROUP=military ha sia dispiegamenti attivi che vecchi; il resto lo etichettiamo per query
            sats.append(dict(name=name, norad=norad, cat=cat, nation=nat, role=role, inc=inc, period_min=period_min, tle1=l1, tle2=l2))
        time.sleep(0.4)
    if not sats:
        raise RuntimeError("nessun TLE ricevuto: " + "; ".join(errors[:5]))
    # priorita': ISR/SAR/SIGINT/EW prima dei comms; taglio a SAT_MAX
    order = {"ISR": 0, "SAR": 1, "SIGINT": 2, "EW": 3, "SSA": 4, "MIL": 5, "COMMS": 6}
    sats.sort(key=lambda x: (order.get(x["cat"], 9), x["name"]))
    sats = sats[:SAT_MAX]
    by_cat, by_nat = {}, {}
    for x in sats:
        by_cat[x["cat"]] = by_cat.get(x["cat"], 0) + 1
        by_nat[x["nation"]] = by_nat.get(x["nation"], 0) + 1
    return dict(schema="owi-sats/1", generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source="CelesTrak GP (TLE pubblici, 18 SDS). I satelliti NRO/GRU classificati non hanno elementi pubblici e non compaiono.",
                count=len(sats), by_cat=by_cat, by_nation=by_nat, errors=errors, sats=sats)


# ---------------------------------------------------------------------------
# FLOTTA USA — USNI News Fleet & Marine Tracker (settimanale, regione + data)
# ---------------------------------------------------------------------------
USNI_FEED = "https://news.usni.org/category/fleet-tracker/feed"
# centroidi approssimati delle regioni citate da USNI (lat, lon, raggio km dell'incertezza)
USNI_REGIONS = {
    "eastern mediterranean": (34.0, 30.0, 500), "central mediterranean": (36.0, 15.0, 500), "western mediterranean": (38.0, 2.0, 500),
    "mediterranean sea": (35.5, 18.0, 900), "mediterranean": (35.5, 18.0, 900), "adriatic": (43.0, 15.0, 300), "aegean": (38.0, 25.0, 300),
    "red sea": (20.0, 38.5, 600), "gulf of aden": (12.5, 47.0, 400), "arabian sea": (16.0, 63.0, 800), "gulf of oman": (24.5, 58.5, 300),
    "persian gulf": (26.5, 52.0, 400), "arabian gulf": (26.5, 52.0, 400), "north arabian sea": (20.0, 63.0, 600), "indian ocean": (-5.0, 75.0, 1500),
    "south china sea": (13.0, 114.0, 800), "east china sea": (28.0, 125.0, 500), "philippine sea": (18.0, 132.0, 900), "sea of japan": (39.0, 134.0, 500),
    "yellow sea": (36.0, 123.0, 300), "taiwan strait": (24.5, 119.5, 200), "western pacific": (20.0, 140.0, 1500), "eastern pacific": (25.0, -125.0, 1500),
    "central pacific": (15.0, 175.0, 1500), "pacific ocean": (15.0, 165.0, 2500), "pacific": (15.0, 165.0, 2500), "north pacific": (40.0, 170.0, 1500),
    "atlantic ocean": (35.0, -45.0, 2500), "western atlantic": (33.0, -70.0, 900), "eastern atlantic": (40.0, -20.0, 900), "north atlantic": (50.0, -30.0, 1500),
    "atlantic": (35.0, -45.0, 2500), "caribbean": (15.0, -72.0, 800), "caribbean sea": (15.0, -72.0, 800), "gulf of mexico": (25.0, -90.0, 500),
    "north sea": (56.0, 3.0, 400), "baltic sea": (57.5, 19.0, 400), "baltic": (57.5, 19.0, 400), "norwegian sea": (68.0, 5.0, 600), "barents sea": (73.0, 35.0, 600),
    "black sea": (43.0, 34.0, 400), "arctic": (75.0, 0.0, 1500), "bay of bengal": (14.0, 88.0, 700), "andaman sea": (10.0, 96.0, 400), "java sea": (-5.0, 111.0, 400),
    "coral sea": (-16.0, 152.0, 700), "tasman sea": (-38.0, 160.0, 700), "gulf of alaska": (56.0, -145.0, 600), "bering sea": (58.0, -175.0, 700),
    "san diego": (32.7, -117.2, 30), "norfolk": (36.9, -76.3, 30), "mayport": (30.4, -81.4, 30), "pearl harbor": (21.35, -157.95, 30), "guam": (13.45, 144.7, 60),
    "yokosuka": (35.29, 139.67, 30), "sasebo": (33.16, 129.72, 30), "singapore": (1.3, 103.8, 40), "manama": (26.2, 50.6, 30), "bahrain": (26.2, 50.6, 30),
    "rota": (36.62, -6.35, 30), "gaeta": (41.21, 13.57, 30), "souda bay": (35.49, 24.15, 30), "naples": (40.83, 14.25, 30), "everett": (47.98, -122.2, 30),
    "bremerton": (47.56, -122.63, 30), "kitsap": (47.72, -122.71, 30), "japan": (35.0, 138.0, 400), "australia": (-25.0, 134.0, 1500), "hawaii": (21.0, -157.5, 300),
    "diego garcia": (-7.3, 72.4, 60), "djibouti": (11.6, 43.1, 60), "portsmouth": (50.8, -1.1, 30), "faslane": (56.07, -4.82, 30), "crete": (35.3, 24.5, 100),
}
HULL_TYPES = {"CVN": "carrier", "CV": "carrier", "LHA": "amphib", "LHD": "amphib", "LPD": "amphib", "LSD": "amphib", "CG": "cruiser", "DDG": "destroyer",
              "FFG": "frigate", "LCS": "corvette", "SSN": "submarine", "SSGN": "submarine", "SSBN": "submarine", "ESB": "auxiliary", "ESD": "auxiliary",
              "EPF": "auxiliary", "T-AKE": "auxiliary", "T-AO": "auxiliary", "T-AH": "auxiliary", "AS": "auxiliary", "MCM": "minesweeper", "PC": "patrol"}
SHIP_RE = re.compile(r"\b(USS|USNS|USCGC)\s+([A-Z][A-Za-z\.\-'’ ]{1,40}?)\s+\((T-)?([A-Z]{1,4})[- ]?(\d{1,4})\)")


def _region_of(text):
    t = text.lower()
    best = None
    for k, v in USNI_REGIONS.items():
        pos = t.find(k)
        if pos >= 0 and (best is None or pos < best[0] or (pos == best[0] and len(k) > len(best[1]))):
            best = (pos, k, v)
    return (best[1], best[2]) if best else (None, None)


def build_fleet():
    xml = fetch(USNI_FEED, timeout=40).decode("utf-8", "replace")
    # parsing a regex sul primo <item>: il feed USNI e' lungo e a volte tronco/mal formato
    mi = re.search(r"<item>(.*?)(</item>|$)", xml, re.S)
    if not mi:
        raise RuntimeError("feed USNI senza <item>")
    it = mi.group(1)

    def _tag(name):
        m = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", it, re.S)
        return (m.group(1) if m else "").strip()
    title, link, pubraw = _tag("title"), _tag("link"), _tag("pubDate")
    try:
        pub = parsedate_to_datetime(pubraw).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        pub = pubraw[:25]
    mc = re.search(r"<content:encoded><!\[CDATA\[(.*?)(\]\]></content:encoded>|$)", it, re.S)
    body = mc.group(1) if mc else _tag("description")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    # spezza per paragrafi/titoli prima di togliere i tag
    body = re.sub(r"</(p|h[1-6]|div|li)>", "\n", body)
    text = re.sub(r"<[^>]+>", " ", body)
    import html as _html
    text = _html.unescape(text)
    m = re.search(r"as of ([A-Z][a-z]+\.? \d{1,2}, \d{4})", text)
    as_of = m.group(1) if m else pub[:10]
    # sezioni: righe che iniziano con "In the X" / "In X"
    ships, region, region_geo, region_line = [], None, None, ""
    seen = set()
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if re.match(r"^In (the )?[A-Z]", line) and len(line) < 60:
            region_line = line
            region, region_geo = _region_of(line)
            continue
        for mm in SHIP_RE.finditer(line):
            prefix, name, tprefix, cls, num = mm.groups()
            hull = f"{tprefix or ''}{cls}-{num}"
            if hull in seen:
                continue
            seen.add(hull)
            stype = HULL_TYPES.get((tprefix or "") + cls, HULL_TYPES.get(cls, "other"))
            # contesto: la frase che contiene la nave
            ctx = re.sub(r"\s+", " ", line)[:220]
            in_port = bool(re.search(r"\bin port\b|pierside|moored", ctx, re.I)) or bool(region_geo and region_geo[2] <= 60)
            ships.append(dict(name=f"{prefix} {name.strip()}", hull=hull, type=stype, nation="USA",
                              region=region_line or "n/d", region_key=region,
                              lat=region_geo[0] if region_geo else None, lng=region_geo[1] if region_geo else None,
                              radius_km=region_geo[2] if region_geo else None, status="in porto" if in_port else "in mare", context=ctx))
    located = sum(1 for x in ships if x["lat"] is not None)
    return dict(schema="owi-fleet/1", generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source="USNI News Fleet & Marine Tracker", title=title, link=link, published=pub, as_of=as_of,
                note="Posizioni = centroide della regione citata da USNI (approssimate, raggio dichiarato). Non e' AIS.",
                count=len(ships), located=located, ships=ships)


# ---------------------------------------------------------------------------
# AIS militare — aisstream.io (websocket, chiave gratuita). Solo con AISSTREAM_KEY.
# ---------------------------------------------------------------------------
AIS_SECONDS = int(os.environ.get("OWI_AIS_SECONDS", "150"))
NAVAL_NAME_RE = re.compile(r"\b(WARSHIP|NAVY|NAVAL|USS |HMS |HMCS |HMAS |FGS |FS |ITS |ESPS |HNLMS |BNS |HDMS |HNOMS |HSWMS |TCG |ROKS |JS |INS |RFS |KRI |BRP |HTMS |RSS |ORP |HS |NRP |SPS |JMSDF|COAST ?GUARD|PATROL|FRIGATE|DESTROYER|CORVETTE|SUBMARINE)\b")


def build_ais(static_cache):
    key = os.environ.get("AISSTREAM_KEY", "").strip()
    if not key:
        raise RuntimeError("AISSTREAM_KEY non configurata (GitHub Secret)")
    import asyncio
    try:
        import websockets  # noqa: F401
    except ImportError as e:
        raise RuntimeError("modulo websockets mancante: pip install websockets") from e

    positions, static = {}, dict(static_cache or {})

    async def run():
        import websockets
        deadline = time.time() + AIS_SECONDS
        async with websockets.connect("wss://stream.aisstream.io/v0/stream", max_size=2**22) as ws:
            await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": [[[-85, -180], [85, 180]]],
                                      "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                meta = msg.get("MetaData", {})
                mmsi = str(meta.get("MMSI", ""))
                if not mmsi:
                    continue
                if msg.get("MessageType") == "ShipStaticData":
                    sd = msg["Message"]["ShipStaticData"]
                    static[mmsi] = dict(name=(sd.get("Name") or "").strip(), type=sd.get("Type"), callsign=(sd.get("CallSign") or "").strip(),
                                        dest=(sd.get("Destination") or "").strip(), ts=int(time.time()))
                elif msg.get("MessageType") == "PositionReport":
                    pr = msg["Message"]["PositionReport"]
                    positions[mmsi] = dict(lat=round(pr.get("Latitude", 0), 4), lng=round(pr.get("Longitude", 0), 4), sog=pr.get("Sog"),
                                           cog=pr.get("Cog"), heading=pr.get("TrueHeading"), name=(meta.get("ShipName") or "").strip(),
                                           ts=meta.get("time_utc", ""))

    asyncio.run(run())
    # pulizia cache statica: 30 giorni
    cutoff = int(time.time()) - 30 * 86400
    static = {k: v for k, v in static.items() if v.get("ts", 0) >= cutoff}

    def is_naval(mmsi, name):
        st = static.get(mmsi, {})
        if st.get("type") == 35:
            return "AIS tipo 35 (military ops)"
        nm = (name or st.get("name") or "").upper()
        if NAVAL_NAME_RE.search(nm):
            return "nome navale"
        return None

    ships = []
    for mmsi, p in positions.items():
        why = is_naval(mmsi, p["name"])
        if not why:
            continue
        st = static.get(mmsi, {})
        ships.append(dict(mmsi=mmsi, name=p["name"] or st.get("name") or mmsi, lat=p["lat"], lng=p["lng"], sog=p["sog"], cog=p["cog"],
                          heading=p["heading"], dest=st.get("dest", ""), why=why, ts=p["ts"][:19]))
    return dict(schema="owi-ais/1", generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source="aisstream.io (AIS terrestre, copertura costiera)", window_s=AIS_SECONDS, positions_seen=len(positions),
                static_known=len(static), count=len(ships), ships=ships), static


def main():
    args = sys.argv[1:]
    out = args[args.index("--out") + 1] if "--out" in args else "out"
    os.makedirs(out, exist_ok=True)
    try:
        f = build_firms()
        json.dump(f, open(os.path.join(out, "firms.json"), "w"), separators=(",", ":"))
        print(f"[aux] FIRMS: {f['total_in_theatres']} hotspot nei teatri, {f['shown']} scritti, per zona {f['by_zone']}")
    except Exception as e:  # noqa: BLE001
        print(f"[aux] FIRMS non disponibile: {e}", file=sys.stderr)
    try:
        n = build_news()
        json.dump(n, open(os.path.join(out, "news.json"), "w"), separators=(",", ":"), ensure_ascii=False)
        ok = sum(1 for v in n["feeds"].values() if isinstance(v, int))
        print(f"[aux] NEWS: {n['count']} notizie da {ok}/{len(RSS_FEEDS)} feed")
    except Exception as e:  # noqa: BLE001
        print(f"[aux] NEWS non disponibile: {e}", file=sys.stderr)
    try:
        s = build_satellites()
        json.dump(s, open(os.path.join(out, "satellites.json"), "w"), separators=(",", ":"))
        print(f"[aux] SAT: {s['count']} TLE, per categoria {s['by_cat']}, errori {len(s['errors'])}")
    except Exception as e:  # noqa: BLE001
        print(f"[aux] SAT non disponibile: {e}", file=sys.stderr)
    try:
        fl = build_fleet()
        json.dump(fl, open(os.path.join(out, "fleet.json"), "w"), separators=(",", ":"), ensure_ascii=False)
        print(f"[aux] FLEET: {fl['count']} navi USNI ({fl['located']} con regione), as of {fl['as_of']}")
    except Exception as e:  # noqa: BLE001
        print(f"[aux] FLEET non disponibile: {e}", file=sys.stderr)
    cache_path = os.path.join(out, "ais-static.json")
    try:
        cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    except ValueError:
        cache = {}
    try:
        a, cache = build_ais(cache)
        json.dump(a, open(os.path.join(out, "ais-mil.json"), "w"), separators=(",", ":"), ensure_ascii=False)
        json.dump(cache, open(cache_path, "w"), separators=(",", ":"))
        print(f"[aux] AIS: {a['count']} navi militari su {a['positions_seen']} posizioni in {AIS_SECONDS}s")
    except Exception as e:  # noqa: BLE001
        print(f"[aux] AIS non disponibile: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
