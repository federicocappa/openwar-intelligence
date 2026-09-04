"""Test end-to-end con memoria sintetica (nessuna rete).

Genera 40 giorni di osservazioni: traffico normale per teatro, un pacchetto
d'attacco piantato nell'ultimo giorno su iran-gulf, spike GDELT dopo i giorni
con surge. Verifica che gli indicatori scattino dove devono e non altrove.
Uso: python tests/test_pipeline.py   (usa una memoria temporanea, non tocca memory/)
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="owi-brain-test-")
store.MEM = os.path.join(TMP, "memory")
store.DB_PATH = os.path.join(TMP, "cache.db")
import run_all  # noqa: E402
import learning  # noqa: E402

run_all.OUT = os.path.join(TMP, "out")
learning.MODEL_PATH = os.path.join(TMP, "model.json")

from zones import ZONES  # noqa: E402

random.seed(7)
DAYS = 40
START = datetime(2026, 7, 25)
NORMAL = {  # velivoli distinti/giorno per bucket, per teatro (ordine di grandezza realistico)
    "ukraine": dict(fighter=2, tanker=1, awacs=1, isr=3, transport=4, helicopter=1, bomber=0),
    "iran-gulf": dict(fighter=3, tanker=2, awacs=1, isr=2, transport=6, helicopter=2, bomber=0),
    "nato-baltic": dict(fighter=4, tanker=1, awacs=1, isr=2, transport=3, helicopter=1, bomber=0),
    "red-sea": dict(fighter=1, tanker=1, awacs=0, isr=1, transport=2, helicopter=1, bomber=0),
}
ROLE_TYPE = dict(fighter="F16", tanker="K35R", awacs="E3TF", isr="RC135", transport="C17", helicopter="H60", bomber="B52")
SURGE_DAYS = {DAYS - 1: "iran-gulf", DAYS - 12: "iran-gulf", DAYS - 25: "nato-baltic"}


def gen_day(i):
    d = START + timedelta(days=i)
    ds = d.strftime("%Y-%m-%d")
    run_id = ds + "T04:20Z"
    rows = []
    for z in ZONES:
        base = NORMAL.get(z["id"], dict(fighter=0, tanker=0, awacs=0, isr=1, transport=1, helicopter=0, bomber=0))
        surge = SURGE_DAYS.get(i) == z["id"]
        for role, n in base.items():
            n = max(0, n + random.choice([-1, 0, 0, 1]))
            if surge:
                n += dict(fighter=8, tanker=4, awacs=2, isr=3, bomber=2).get(role, 0)
            for k in range(n):
                hx = f"{z['id'][:2]}{role[:2]}{k:02d}"  # cellule stabili nel tempo -> profili
                for s in range(4):
                    ts = (d + timedelta(hours=4, minutes=20 + 5 * s)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    # pacchetto: tutti vicini alla cisterna 0
                    lat = z["lat"] + (random.uniform(-0.8, 0.8) if not surge else random.uniform(-0.3, 0.3))
                    lon = z["lon"] + (random.uniform(-0.8, 0.8) if not surge else random.uniform(-0.3, 0.3))
                    rows.append(dict(ts=ts, run_id=run_id, hex=hx, callsign=f"{role.upper()[:4]}{k:02d}", reg="", type_code=ROLE_TYPE[role],
                                     role=role, nation="USA", lat=lat, lon=lon, alt=25000, gs=400, track=90, squawk="",
                                     zone=z["id"], ring="core"))
    store.append("aircraft_obs", rows, date=ds)
    g = []
    for z in ZONES:
        v = random.uniform(0.5, 1.5)
        for k in range(1, 4):  # spike nei 3 giorni dopo un surge
            if SURGE_DAYS.get(i - k) == z["id"]:
                v += 6.0
        g.append(dict(date=ds, zone=z["id"], vol_strike=round(v, 3), fetched_at=run_id))
    store.append("gdelt_daily", g, date=ds)
    store.append("threat_scores", [dict(run_id=run_id, zone=z["id"], score=50, level="watch", fetched_at=run_id) for z in ZONES], date=ds)
    return ds, run_id


try:
    last = None
    for i in range(DAYS):
        ds, run_id = gen_day(i)
        if i >= DAYS - 3:  # gli ultimi run producono anche indicatori/storico
            last = run_all.analyse(run_id, ds)
    report = last
    z = {zo["id"]: zo for zo in report["zones"]}
    ig = z["iran-gulf"]
    act = set(ig["active_indicators"])
    print("\nATTIVI iran-gulf:", sorted(act))
    assert "Surge di aerocisterne" in act and "Massa di caccia" in act, "surge non rilevato"
    assert ig["level"] in ("alert", "elevated"), ig["level"]
    assert ig["strike_packages"], "strike package non rilevato"
    assert report["zones"][0]["id"] == "iran-gulf", "iran-gulf dovrebbe essere in cima"
    quiet = [zo for zo in report["zones"] if zo["id"] in ("ukraine", "red-sea")]
    assert all(zo["level"] in ("quiet", "watch") for zo in quiet), [(q["id"], q["level"], q["active_indicators"]) for q in quiet]
    assert report["memory"]["profiled"] > 20, report["memory"]
    print("profili:", report["memory"]["profiled"], "| modello:", report["model"]["mode"], "-", report["model"].get("reason_it"))
    print("\nOK: pipeline verificata")
finally:
    if "--keep" in sys.argv:
        shutil.copy(os.path.join(run_all.OUT, "iw-report.json"), "/tmp/owi-iw-report-synthetic.json")
        print("report sintetico copiato in /tmp/owi-iw-report-synthetic.json")
    shutil.rmtree(TMP, ignore_errors=True)
