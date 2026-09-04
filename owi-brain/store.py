"""Memoria persistente.

Sorgente di verita': file append-only per giorno in memory/<tabella>/YYYY-MM-DD.jsonl.gz
(piccoli, immutabili, adatti a git). Il DB SQLite e' una cache ricostruita ad ogni
run per fare le query; non va committato.
"""
import gzip
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(ROOT, "memory")
DB_PATH = os.path.join(ROOT, "cache.db")

TABLES = {
    "aircraft_obs": "(ts TEXT, run_id TEXT, hex TEXT, callsign TEXT, reg TEXT, type_code TEXT, role TEXT, "
                    "nation TEXT, lat REAL, lon REAL, alt INT, gs REAL, track REAL, squawk TEXT, zone TEXT, ring TEXT)",
    "gdelt_daily": "(date TEXT, zone TEXT, vol_strike REAL, fetched_at TEXT)",
    "threat_scores": "(run_id TEXT, zone TEXT, score INT, level TEXT, fetched_at TEXT)",
    "runs": "(run_id TEXT, started_at TEXT, samples INT, n_aircraft INT, notes TEXT)",
    "indicator_hist": "(date TEXT, run_id TEXT, zone TEXT, indicator TEXT, value REAL, mean REAL, std REAL, z REAL, active INT)",
    "scores_hist": "(date TEXT, run_id TEXT, zone TEXT, composite REAL, rule_score REAL, model_p REAL, level TEXT)",
}


def utcnow():
    return datetime.now(timezone.utc)


def today_str(dt=None):
    return (dt or utcnow()).strftime("%Y-%m-%d")


def append(table, rows, date=None):
    """Aggiunge righe al file del giorno."""
    if not rows:
        return
    d = os.path.join(MEM, table)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{date or today_str()}.jsonl.gz")
    with gzip.open(path, "at", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def iter_rows(table, since_date=None):
    d = os.path.join(MEM, table)
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl.gz"):
            continue
        day = fn[:-9]
        if since_date and day < since_date:
            continue
        with gzip.open(os.path.join(d, fn), "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def rebuild_db(since_date=None):
    """Ricostruisce la cache SQLite dai file memoria."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    for t, ddl in TABLES.items():
        con.execute(f"CREATE TABLE {t} {ddl}")
        cols = [c.split()[0] for c in ddl.strip("()").split(",")]
        rows = [tuple(r.get(c) for c in cols) for r in iter_rows(t, since_date)]
        if rows:
            con.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(cols))})", rows)
    con.execute("CREATE INDEX IF NOT EXISTS i_obs_zone ON aircraft_obs(zone, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS i_obs_hex ON aircraft_obs(hex)")
    con.commit()
    return con


def days_of_memory():
    d = os.path.join(MEM, "aircraft_obs")
    if not os.path.isdir(d):
        return 0
    return len([f for f in os.listdir(d) if f.endswith(".jsonl.gz")])
