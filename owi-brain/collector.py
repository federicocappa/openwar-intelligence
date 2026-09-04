"""Collector: fotografa il mondo e lo scrive in memoria.

Fonti (tutte senza chiave):
  - adsb.lol /v2/mil      velivoli militari in volo, SAMPLES campioni a INTERVAL_MIN
  - GDELT DOC API         volume articoli "colpi" per zona (velocita' notizie + ground truth)
  - threat-board.json     punteggi OWI del run precedente (dal sito o dal repo)
"""
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

import classify
import store
from zones import ZONES, locate

UA = {"User-Agent": "OWI-brain/1.0 (+https://openwarintelligence.org)"}
ADSB_URL = "https://api.adsb.lol/v2/mil"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
THREAT_URL = os.environ.get("OWI_THREAT_URL", "https://openwarintelligence.org/data/threat-board.json")
LIVE_SAMPLES_URL = os.environ.get("OWI_LIVE_SAMPLES_URL",
    "https://raw.githubusercontent.com/federicocappa/openwar-intelligence/live/samples/{date}.jsonl.gz")
SAMPLES = int(os.environ.get("OWI_SAMPLES", "4"))
INTERVAL_MIN = float(os.environ.get("OWI_INTERVAL_MIN", "5"))


def http_json(url, timeout=40, retries=2, backoff=(3, 6, 12)):
    """GET JSON con retry. Sui 429 (GDELT limita gli IP condivisi di GitHub) aspetta di piu'."""
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace").strip()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            last = e
            wait = backoff[min(i, len(backoff) - 1)]
            if e.code == 429:
                wait = max(wait, 25 * (i + 1))
            time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(backoff[min(i, len(backoff) - 1)])
    print(f"  [warn] {url[:80]} -> {last}", file=sys.stderr)
    return None


def sample_aircraft(run_id):
    data = http_json(ADSB_URL)
    if not data or not isinstance(data.get("ac"), list):
        return []
    ts = store.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for a in data["ac"]:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        zone, ring = locate(lat, lon)
        role = classify.role_of(a.get("t"), a.get("flight"))
        alt = a.get("alt_baro")
        alt = 0 if alt in (None, "ground") else alt
        rows.append(dict(
            ts=ts, run_id=run_id, hex=(a.get("hex") or "").lower(), callsign=(a.get("flight") or "").strip(),
            reg=a.get("r") or "", type_code=(a.get("t") or "").upper(), role=role,
            nation=classify.nation_of(a.get("hex")), lat=round(lat, 4), lon=round(lon, 4), alt=int(alt or 0),
            gs=round(a.get("gs") or 0, 1), track=round(a.get("track") or 0, 1), squawk=a.get("squawk") or "",
            zone=zone, ring=ring,
        ))
    return rows


def collect_aircraft(run_id):
    total = 0
    for i in range(SAMPLES):
        rows = sample_aircraft(run_id)
        store.append("aircraft_obs", rows)
        in_zone = sum(1 for r in rows if r["zone"])
        print(f"  campione {i + 1}/{SAMPLES}: {len(rows)} velivoli, {in_zone} nei teatri")
        total += len(rows)
        if i < SAMPLES - 1:
            time.sleep(INTERVAL_MIN * 60)
    return total


def collect_live_samples(days=2):
    """Unisce alla memoria i campioni raccolti ogni 10 minuti dal workflow live (branch `live`).
    Dedup per (ts, hex) contro cio' che e' gia' in memoria per quel giorno."""
    total = 0
    for k in range(days):
        day = store.today_str(store.utcnow() - timedelta(days=k))
        url = LIVE_SAMPLES_URL.format(date=day)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                blob = r.read()
        except Exception as e:  # noqa: BLE001
            print(f"  live {day}: non disponibile ({e})")
            continue
        rows = []
        with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        seen = {(r["ts"], r["hex"]) for r in store.iter_rows("aircraft_obs", since_date=day) if r["ts"][:10] == day}
        new = [r for r in rows if (r["ts"], r["hex"]) not in seen]
        store.append("aircraft_obs", new, date=day)
        total += len(new)
        print(f"  live {day}: {len(rows)} campioni, {len(new)} nuovi in memoria")
    return total


def collect_gdelt(days_back=3):
    """timelinevol restituisce % del volume globale per giorno; prendiamo gli ultimi giorni
    (il valore di ieri si stabilizza solo a fine giornata, quindi ri-scriviamo 3 giorni)."""
    fetched = store.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    n = 0
    for z in ZONES:
        q = urllib.parse.urlencode(dict(query=z["gdelt"], mode="timelinevol", timespan=f"{days_back + 1}d", format="json"))
        d = http_json(f"{GDELT_URL}?{q}", timeout=60, retries=3)
        rows = []
        try:
            for pt in d["timeline"][0]["data"]:
                rows.append(dict(date=pt["date"][:8].replace(" ", ""), zone=z["id"], vol_strike=float(pt["value"]), fetched_at=fetched))
        except (TypeError, KeyError, IndexError):
            pass
        rows = [dict(r, date=f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}") for r in rows]
        if rows:
            store.append("gdelt_daily", rows)
            n += len(rows)
        time.sleep(8)  # GDELT: ~1 richiesta ogni 5 s per IP, gli IP dei runner sono condivisi
    print(f"  GDELT: {n} punti/giorno scritti")
    return n


def collect_threat_scores():
    d = http_json(THREAT_URL)
    if not d or "zones" not in d:
        local = os.path.join(store.ROOT, "..", "data", "threat-board.json")
        if os.path.exists(local):
            d = json.load(open(local, encoding="utf-8"))
    if not d or "zones" not in d:
        print("  threat-board: non disponibile")
        return 0
    fetched = store.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    rows = [dict(run_id=d.get("run_id"), zone=z["id"], score=z.get("score"), level=z.get("level"), fetched_at=fetched)
            for z in d["zones"]]
    # evita duplicati se il run del threat board non e' cambiato
    seen = {(r["run_id"], r["zone"]) for r in store.iter_rows("threat_scores", since_date=store.today_str(store.utcnow() - timedelta(days=3)))}
    rows = [r for r in rows if (r["run_id"], r["zone"]) not in seen]
    store.append("threat_scores", rows)
    print(f"  threat-board: {len(rows)} punteggi nuovi (run {d.get('run_id')})")
    return len(rows)


def run(run_id):
    print("[collector] velivoli (campioni diretti)")
    n = collect_aircraft(run_id)
    print("[collector] velivoli (feed live ogni 10 min)")
    n += collect_live_samples()
    print("[collector] GDELT")
    collect_gdelt()
    print("[collector] threat-board")
    collect_threat_scores()
    store.append("runs", [dict(run_id=run_id, started_at=run_id, samples=SAMPLES, n_aircraft=n, notes="")])
    return n


if __name__ == "__main__":
    run(store.utcnow().strftime("%Y-%m-%dT%H:%MZ"))
