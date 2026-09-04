"""Run completo: raccolta -> memoria -> baseline -> indicatori -> profili -> fusione -> apprendimento -> report.

Uso:  python run_all.py            (raccoglie e analizza)
      python run_all.py --no-collect   (solo analisi sulla memoria esistente)
Output: out/iw-report.json (stato completo), out/iw-history.json (serie compatta per grafici)
"""
import json
import os
import sys

import features
import fusion
import learning
import profiles as prof
import store
from indicators import INDICATORS, evaluate_zone, level_of
from zones import ZONES

OUT = os.path.join(store.ROOT, "out")
BASELINE_DAYS = 45


def analyse(run_id, date):
    con = store.rebuild_db()
    dates = features.observed_dates(con)
    if date not in dates:
        print("[analisi] nessuna osservazione per oggi; uso l'ultimo giorno disponibile")
        date = dates[-1] if dates else date
    hist_dates = [d for d in dates if d < date][-BASELINE_DAYS:]
    feats_by_date = {d: features.daily_features(con, d) for d in hist_dates + [date]}
    today = feats_by_date[date]
    profs = prof.build_profiles(con, date)
    anomalies = prof.individual_anomalies(con, date, profs)
    packages = fusion.strike_packages(con, date)
    orbits = fusion.persistent_orbits(con, date)
    # indicatori (scritti in memoria PRIMA dell'apprendimento, cosi' fanno dataset)
    zones_out, ind_rows, score_rows = [], [], []
    for z in ZONES:
        zid = z["id"]
        history = [(d, feats_by_date[d][zid]) for d in hist_dates]
        composite, inds = evaluate_zone(zid, today[zid], history)
        for i in inds:
            ind_rows.append(dict(date=date, run_id=run_id, zone=zid, indicator=i["id"], value=i["value"],
                                 mean=i["baseline_mean"], std=i["baseline_std"], z=i["z"], active=int(i["active"])))
        zones_out.append(dict(id=zid, name_it=z["name_it"], lat=z["lat"], lon=z["lon"], radius_km=z["r"],
                              rule_score=round(composite, 1), indicators=inds,
                              counts={k: int(v) for k, v in today[zid].items() if k in features.BUCKETS or k in ("all", "approach_all")},
                              nations=today[zid].get("_nations", []),
                              strike_packages=[p for p in packages if p["zone"] == zid][:5],
                              orbits=[o for o in orbits if o["zone"] == zid],
                              anomalies=[a for a in anomalies if a["zone"] == zid][:8]))
    # de-duplica indicator_hist per (date, zone): un run al giorno, ma se rigirato sostituisce
    existing = {(r["date"], r["zone"], r["indicator"]) for r in store.iter_rows("indicator_hist", since_date=date)}
    store.append("indicator_hist", [r for r in ind_rows if (r["date"], r["zone"], r["indicator"]) not in existing], date=date)
    con = store.rebuild_db()
    # apprendimento
    status = learning.fit_and_validate(con)
    model = learning.load_model()
    for zo in zones_out:
        zvec = [next(i["z"] for i in zo["indicators"] if i["id"] == f) for f in learning.FEATURE_IDS]
        p = learning.predict(model, zvec) if model else None
        zo["model_p"] = None if p is None else round(p, 3)
        zo["score"] = round(0.5 * zo["rule_score"] + 50 * p, 1) if p is not None else zo["rule_score"]
        zo["level"] = level_of(zo["score"])
        zo["active_indicators"] = [i["name_it"] for i in zo["indicators"] if i["active"]]
        score_rows.append(dict(date=date, run_id=run_id, zone=zo["id"], composite=zo["score"], rule_score=zo["rule_score"],
                               model_p=zo["model_p"], level=zo["level"]))
    existing = {(r["date"], r["zone"]) for r in store.iter_rows("scores_hist", since_date=date)}
    store.append("scores_hist", [r for r in score_rows if (r["date"], r["zone"]) not in existing], date=date)
    zones_out.sort(key=lambda zo: -zo["score"])
    # report
    n_days = store.days_of_memory()
    n_obs = con.execute("SELECT COUNT(*) FROM aircraft_obs").fetchone()[0]
    n_hex = con.execute("SELECT COUNT(DISTINCT hex) FROM aircraft_obs").fetchone()[0]
    top_prof = sorted(profs.values(), key=lambda p: -p["n_days"])[:30]
    report = dict(
        schema="owi-iw/1", run_id=run_id, date=date, generated_at=store.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        memory=dict(days=n_days, observations=n_obs, airframes=n_hex, profiled=len(profs), baseline_days=len(hist_dates)),
        model=status, method_it=(
            "Indicatori I&W valutati contro la baseline storica di ogni teatro (z-score, finestra 45 giorni). "
            "Punteggio = somma pesata degli z-score attivi. Il modello appreso si attiva solo con dati sufficienti "
            "e solo se batte la regola su holdout temporale; l'etichetta e' un proxy (spike GDELT o salto Threat Board entro 72h)."),
        indicators_catalog=[dict(id=i[0], name_it=i[4], weight=i[2], why_it=i[5]) for i in INDICATORS],
        zones=zones_out, global_strike_packages=packages[:10], global_anomalies=anomalies[:15],
        profiles_sample=top_prof,
    )
    os.makedirs(OUT, exist_ok=True)
    json.dump(report, open(os.path.join(OUT, "iw-report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # storico compatto
    hist = {}
    for r in store.iter_rows("scores_hist"):
        hist.setdefault(r["zone"], []).append([r["date"], r["composite"], r["level"]])
    json.dump(dict(schema="owi-iw-history/1", generated_at=report["generated_at"], zones=hist),
              open(os.path.join(OUT, "iw-history.json"), "w"), separators=(",", ":"))
    print(f"[report] {n_days} giorni di memoria, {n_obs} osservazioni, {n_hex} cellule, modello: {status['mode']}")
    for zo in zones_out[:5]:
        print(f"  {zo['score']:5.1f} {zo['level']:8s} {zo['name_it']}  attivi: {', '.join(zo['active_indicators']) or '-'}")
    return report


def main():
    run_id = store.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    date = store.today_str()
    if "--no-collect" not in sys.argv:
        import collector
        collector.run(run_id)
    analyse(run_id, date)


if __name__ == "__main__":
    main()
