"""Fonti ausiliarie lette dal brain (ogni ora, dentro il job live) e servite come file statici.

  firms.json  NASA FIRMS VIIRS (Suomi NPP) 24h: hotspot termici entro 888 km dai teatri.
              Nessuna chiave: CSV pubblico. Il browser non lo raggiunge (CORS): lo legge il brain.
  news.json   19 feed RSS (mainstream + OSINT difesa), filtrati per parole chiave militari,
              con data ISO, fonte, teatro stimato. Sostituisce rss2json (bloccato dalla CSP).

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


if __name__ == "__main__":
    main()
