"""Libreria Indications & Warning.

Ogni indicatore e' un precursore noto di operazioni offensive, valutato contro
la sua baseline (z-score). Il punteggio composito e' una somma pesata dei
z-score tagliati a [0, 3], riportata su 0-100. Tutto e' spiegabile: per ogni
zona il report elenca quali indicatori sono attivi e perche'.
"""
from features import baseline, zscore

# (id, feature, peso, soglia_z, nome_it, spiegazione_it)
INDICATORS = [
    ("tanker_surge",     "tanker",             3.0, 1.5, "Surge di aerocisterne",
     "Le cisterne in orbita sono il collo di bottiglia di ogni pacchetto d'attacco a lungo raggio: piu' cisterne del normale = piu' caccia armati in attesa."),
    ("awacs_coverage",   "awacs",              2.5, 1.5, "Copertura AWACS/C2",
     "Un radar volante in stazione fuori dal normale indica gestione dello spazio aereo per un'operazione, non addestramento."),
    ("isr_surge",        "isr",                2.0, 1.5, "Surge ISR",
     "Piu' piattaforme di sorveglianza del solito: raccolta di target e valutazione difese prima di colpire."),
    ("fighter_mass",     "fighter",            2.5, 1.5, "Massa di caccia",
     "Caccia in numero anomalo nel teatro: pattugliamento offensivo o scorta a un pacchetto."),
    ("bomber_presence",  "bomber",             2.5, 1.0, "Bombardieri strategici",
     "Bombardieri nel teatro sono rari: segnale deliberato o preparazione di un colpo a distanza."),
    ("transport_inflow", "transport",          1.5, 1.5, "Afflusso di trasporti",
     "Ponte logistico verso il teatro: munizioni, personale, ricambi. Precede di giorni un'operazione sostenuta."),
    ("staging_mass",     "approach_all",       1.5, 1.5, "Massa in staging",
     "Velivoli che si accumulano nell'anello di avvicinamento (basi avanzate) senza entrare nel teatro."),
    ("new_actors",       "n_nations",          1.0, 1.5, "Nuovi attori",
     "Bandiere nuove nel teatro: allargamento della coalizione o intervento di un terzo."),
    ("night_ops",        "night_share",        1.0, 1.5, "Attivita' notturna",
     "Quota anomala di attivita' nelle ore notturne locali: profilo tipico di operazioni reali, non di addestramento."),
    ("news_velocity",    "news_strike_vol",    1.5, 1.5, "Velocita' notizie (colpi)",
     "Il volume globale di articoli su attacchi nel teatro accelera rispetto alla sua norma."),
    ("threat_delta",     "threat_delta",       1.0, 0.0, "Salto Threat Board",
     "Il punteggio OWI del teatro e' salito di >= 6 punti dal run precedente."),
]
MAX_Z = 3.0


def evaluate_zone(zid, today_feats, history):
    """history: lista (date, feats) dei giorni precedenti per la zona."""
    out = []
    total_w = 0.0
    score = 0.0
    for ind_id, feat, w, thr, name, why in INDICATORS:
        x = today_feats.get(feat, 0.0)
        if ind_id == "threat_delta":
            z = min(max(x / 6.0, 0.0), MAX_Z)  # +6 punti = z 1, +18 = saturo
            mean, std, n = None, None, len(history)
            active = x >= 6
        else:
            mean, std, n = baseline(history, feat)
            z = zscore(x, mean, std)
            min_count = 1 if ind_id in ("bomber_presence", "awacs_coverage", "threat_delta") else 2
            if feat in ("night_share",):
                min_count = 0.0
            active = mean is not None and z >= thr and x >= min_count
        zc = min(max(z, 0.0), MAX_Z)
        score += w * zc
        total_w += w
        out.append(dict(id=ind_id, name_it=name, value=round(x, 2),
                        baseline_mean=None if mean is None else round(mean, 2),
                        baseline_std=None if std is None else round(std, 2),
                        baseline_days=n, z=round(z, 2), active=bool(active), weight=w, why_it=why))
    composite = 100.0 * score / (total_w * MAX_Z) if total_w else 0.0
    return composite, out


def level_of(score):
    if score >= 60:
        return "alert"
    if score >= 35:
        return "elevated"
    if score >= 15:
        return "watch"
    return "quiet"
