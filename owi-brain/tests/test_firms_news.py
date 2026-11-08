"""Test degli ingressi FIRMS e notizie RSS (08/11/2026), senza rete.

Verifica che: (1) i giorni senza fonte sono None e NON entrano nella baseline;
(2) con meno di 5 giorni di dati l'indicatore resta neutro; (3) con 6 giorni di norma e un
balzo oggi l'indicatore scatta; (4) una riga 'unavailable' non viene letta;
(5) il collector non scrive nulla se il feed e' unavailable o di schema vecchio.
Uso: python tests/test_firms_news.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="owi-firms-test-")
store.MEM = os.path.join(TMP, "memory")
store.DB_PATH = os.path.join(TMP, "cache.db")
import collector  # noqa: E402
import features  # noqa: E402
from indicators import evaluate_zone  # noqa: E402

Z = "sudan"
days = [f"2026-11-{d:02d}" for d in range(1, 9)]  # 01..08

# giorni 01-02: nessuna fonte. 03-07: 100 hotspot. 08 (oggi): 600. Il 05 e' 'unavailable' e va ignorato.
for d in days[2:7]:
    store.append("firms_daily", [dict(date=d, zone=Z, hotspots=100, frp_sum=1000.0, status="degraded", fetched_at=d)], date=d)
store.append("firms_daily", [dict(date=days[4], zone=Z, hotspots=0, frp_sum=0.0, status="unavailable", fetched_at=days[4])], date=days[4])
store.append("firms_daily", [dict(date=days[7], zone=Z, hotspots=600, frp_sum=9000.0, status="degraded", fetched_at=days[7])], date=days[7])
for d in days[2:8]:
    store.append("news_daily", [dict(date=d, zone=Z, items=3 if d != days[7] else 20, fetched_at=d)], date=d)
# un'osservazione aerea per giorno, cosi' observed_dates li vede
for d in days:
    store.append("aircraft_obs", [dict(ts=d + "T04:20:00Z", run_id=d, hex="abc", callsign="", reg="", type_code="C17", role="transport",
                                       nation="USA", lat=15.5, lon=32.5, alt=30000, gs=400, track=90, squawk="", zone=Z, ring="core")], date=d)
con = store.rebuild_db()
feats = {d: features.daily_features(con, d)[Z] for d in days}
assert feats[days[0]]["firms_hotspots"] is None and feats[days[0]]["news_items"] is None, "giorno senza fonte deve essere None"
assert feats[days[4]]["firms_hotspots"] == 100.0, "la riga unavailable del 05 non deve sovrascrivere il dato valido"
assert feats[days[7]]["firms_hotspots"] == 600.0 and feats[days[7]]["news_items"] == 20.0

# baseline: i None non contano
m, s, n = features.baseline([(d, feats[d]) for d in days[:7]], "firms_hotspots")
assert n == 5 and m == 100.0, (m, s, n)

# (2) con 3 giorni di storia: neutro
hist3 = [(d, feats[d]) for d in days[2:5]]
comp, inds = evaluate_zone(Z, feats[days[7]], hist3)
th = next(i for i in inds if i["id"] == "thermal_surge")
assert th["active"] is False and th["baseline_mean"] is None and th["z"] == 0.0, th

# (3) con 7 giorni di storia (5 con dato): scatta, con z saturo
comp, inds = evaluate_zone(Z, feats[days[7]], [(d, feats[d]) for d in days[:7]])
th = next(i for i in inds if i["id"] == "thermal_surge")
nw = next(i for i in inds if i["id"] == "news_rss_velocity")
assert th["active"] is True and th["value"] == 600.0 and th["z"] >= 3.0, th
assert nw["active"] is True and nw["value"] == 20.0, nw
# giorno senza fonte oggi: valore None, mai attivo
comp0, inds0 = evaluate_zone(Z, feats[days[0]], [(d, feats[d]) for d in days[1:]])
th0 = next(i for i in inds0 if i["id"] == "thermal_surge")
assert th0["value"] is None and th0["active"] is False and th0["z"] == 0.0

# (5) collector: feed unavailable o schema vecchio -> nessuna riga
collector.http_json = lambda url, **k: dict(schema="owi-firms/1", total_in_theatres=0)  # schema vecchio, senza status
assert collector.collect_firms(date="2026-11-09") == 0
collector.http_json = lambda url, **k: dict(schema="owi-firms/2", status="unavailable", total_in_theatres=None)
assert collector.collect_firms(date="2026-11-09") == 0
collector.http_json = lambda url, **k: dict(schema="owi-firms/2", status="degraded", total_in_theatres=10, by_zone_total={Z: 7}, frp_by_zone={Z: 70.5})
assert collector.collect_firms(date="2026-11-09") == 12
con = store.rebuild_db()
assert features.daily_features(con, "2026-11-09")[Z]["firms_hotspots"] == 7.0
print("OK: FIRMS e notizie verificati")
