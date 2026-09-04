"""Apprendimento con ground truth.

Etichetta per (giorno, zona): 1 se nei 3 giorni successivi il volume GDELT di
articoli su colpi supera baseline + 2 sigma, oppure il punteggio Threat Board
sale di >= 8 punti. E' un proxy dichiarato, non la verita' assoluta.

Modello: regressione logistica (stdlib, nessuna dipendenza) sui z-score degli
indicatori. Si attiva solo con abbastanza dati e solo se batte la regola sul
periodo di holdout ordinato nel tempo. Finche' non ci arriva, il report lo dice.
"""
import json
import math
import os
from datetime import datetime, timedelta

from indicators import INDICATORS

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ROOT, "model.json")
MIN_ROWS, MIN_POS, MIN_NEG = 60, 10, 10
HORIZON_DAYS = 3
FEATURE_IDS = [i[0] for i in INDICATORS]


def _dstr(d):
    return d.strftime("%Y-%m-%d")


def labels(con):
    """Ritorna {(date, zone): 0/1} solo dove l'orizzonte e' gia' osservabile."""
    g = {}
    for date, zone, v in con.execute("SELECT date, zone, AVG(vol_strike) FROM gdelt_daily GROUP BY date, zone"):
        g[(date, zone)] = v or 0.0
    t = {}
    for zone, fetched, score in con.execute("SELECT zone, fetched_at, score FROM threat_scores ORDER BY fetched_at"):
        t.setdefault(zone, []).append((fetched[:10], score))
    out = {}
    dates = sorted({d for d, _ in g})
    if not dates:
        return out
    last = datetime.strptime(dates[-1], "%Y-%m-%d")
    for (date, zone) in list(g):
        d0 = datetime.strptime(date, "%Y-%m-%d")
        if d0 + timedelta(days=HORIZON_DAYS) > last:
            continue
        hist = [g.get((_dstr(d0 - timedelta(days=k)), zone)) for k in range(1, 31)]
        hist = [h for h in hist if h is not None]
        if len(hist) < 7:
            continue
        m = sum(hist) / len(hist)
        s = math.sqrt(sum((h - m) ** 2 for h in hist) / max(len(hist) - 1, 1))
        fut = [g.get((_dstr(d0 + timedelta(days=k)), zone)) for k in range(1, HORIZON_DAYS + 1)]
        fut = [f for f in fut if f is not None]
        spike = bool(fut) and max(fut) > m + 2 * max(s, 0.05 * m, 1e-6)
        jump = False
        ts = t.get(zone, [])
        before = [sc for dd, sc in ts if dd <= date]
        after = [sc for dd, sc in ts if date < dd <= _dstr(d0 + timedelta(days=HORIZON_DAYS))]
        if before and after and max(after) - before[-1] >= 8:
            jump = True
        out[(date, zone)] = 1 if (spike or jump) else 0
    return out


def dataset(con):
    X, y, keys = [], [], []
    lab = labels(con)
    rows = con.execute("SELECT date, zone, indicator, z FROM indicator_hist").fetchall()
    zmap = {}
    for date, zone, ind, z in rows:
        zmap.setdefault((date, zone), {})[ind] = z
    for k, feats in sorted(zmap.items()):
        if k in lab and len(feats) >= len(FEATURE_IDS) - 2:
            X.append([min(max(feats.get(f, 0.0), -3.0), 3.0) for f in FEATURE_IDS])
            y.append(lab[k])
            keys.append(k)
    return X, y, keys


def _sigmoid(v):
    return 1.0 / (1.0 + math.exp(-max(min(v, 30), -30)))


def train_logreg(X, y, epochs=400, lr=0.05, l2=0.01):
    n, d = len(X), len(X[0])
    w, b = [0.0] * d, 0.0
    for _ in range(epochs):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            p = _sigmoid(sum(wj * xj for wj, xj in zip(w, xi)) + b) - yi
            for j in range(d):
                gw[j] += p * xi[j]
            gb += p
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return w, b


def predict(model, zvec):
    return _sigmoid(sum(wj * min(max(x, -3.0), 3.0) for wj, x in zip(model["w"], zvec)) + model["b"])


def auc(scores, y):
    pos = [s for s, t in zip(scores, y) if t == 1]
    neg = [s for s, t in zip(scores, y) if t == 0]
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > q else 0.5 if p == q else 0.0) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def brier(scores, y):
    return sum((s - t) ** 2 for s, t in zip(scores, y)) / len(y)


def fit_and_validate(con):
    """Ritorna lo stato del modello (dict) e lo salva se promosso."""
    X, y, keys = dataset(con)
    n, npos = len(y), sum(y)
    status = dict(mode="rule-based", labeled_rows=n, positives=npos, needed_rows=MIN_ROWS, needed_positives=MIN_POS)
    if n < MIN_ROWS or npos < MIN_POS or n - npos < MIN_NEG:
        status["reason_it"] = f"dati insufficienti: {n}/{MIN_ROWS} giorni-zona etichettati, {npos}/{MIN_POS} eventi positivi"
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        return status
    cut = int(n * 0.7)
    w, b = train_logreg(X[:cut], y[:cut])
    m = dict(w=w, b=b)
    hold = [predict(m, x) for x in X[cut:]]
    rule = [sum(max(z, 0) for z in x) for x in X[cut:]]
    a_model, a_rule = auc(hold, y[cut:]), auc(rule, y[cut:])
    status.update(holdout_rows=n - cut, auc_model=None if a_model is None else round(a_model, 3),
                  auc_rule=None if a_rule is None else round(a_rule, 3), brier_model=round(brier(hold, y[cut:]), 3))
    if a_model is not None and a_model >= 0.60 and (a_rule is None or a_model >= a_rule):
        w, b = train_logreg(X, y)
        model = dict(w=w, b=b, features=FEATURE_IDS, trained_on=n, trained_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
                     auc_holdout=round(a_model, 3), auc_rule_holdout=None if a_rule is None else round(a_rule, 3))
        json.dump(model, open(MODEL_PATH, "w"), indent=1)
        status["mode"] = "learned"
        status["reason_it"] = f"modello promosso: AUC {a_model:.2f} su {n - cut} giorni-zona di holdout (regola: {a_rule if a_rule is None else round(a_rule, 2)})"
    else:
        status["reason_it"] = f"modello non promosso: AUC {a_model} vs regola {a_rule}; resta la regola I&W"
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
    return status


def load_model():
    if os.path.exists(MODEL_PATH):
        return json.load(open(MODEL_PATH))
    return None
