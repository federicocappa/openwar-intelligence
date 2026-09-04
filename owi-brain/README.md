# OWI Brain — memoria e Indications & Warning

Cervello fuori dal browser. Gira su GitHub Actions una volta al giorno, accumula memoria
nel repo, calcola baseline per teatro, valuta indicatori I&W, profila ogni cellula,
rileva pacchetti d'attacco e — quando i dati bastano — addestra e valida un modello.
La dashboard legge solo l'output (`out/iw-report.json`).

Nessuna chiave API, nessuna dipendenza oltre Python 3.12 standard.

## Installazione (una volta)

1. Copia la cartella `owi-brain/` nella root del repo `federicocappa/openwar-intelligence`.
2. Sposta `owi-brain/.github/workflows/owi-brain.yml` in `.github/workflows/owi-brain.yml`
   (root del repo: GitHub legge i workflow solo da lì).
3. Repo → Settings → Actions → General → *Workflow permissions* → **Read and write**.
4. Actions → "OWI Brain (I&W daily)" → **Run workflow** per il primo run.
5. Verifica che compaia `owi-brain/out/iw-report.json` nel repo. Da quel momento la dashboard
   lo legge da `raw.githubusercontent.com` (URL in `IW_REPORT_URL` dentro `monitor-guerra.html`;
   se il branch non è `main`, correggilo lì).

Cadenza: `cron` nel workflow. Un run = ~20 minuti (4 campioni a 5 min). Per passare a 4 run/giorno:
`"20 */6 * * *"`. Repo pubblico = minuti Actions illimitati.

## Cosa fa ogni run

| Fase | Modulo | Output |
|---|---|---|
| Raccolta | `collector.py` | `memory/aircraft_obs/DATA.jsonl.gz`, `memory/gdelt_daily/`, `memory/threat_scores/` |
| Feature per teatro | `features.py` | velivoli distinti per ruolo (core + anello di staging), bandiere, quota notturna, GDELT, Threat Board |
| Baseline e indicatori | `indicators.py` | z-score su 45 giorni; 11 indicatori pesati; punteggio 0-100 spiegato |
| Profili per cellula | `profiles.py` | base di casa, teatri abituali, orari; anomalie individuali |
| Fusione | `fusion.py` | strike package (cisterna + ≥3 caccia/bombardiere + AWACS/ISR entro 300 km), orbite persistenti |
| Apprendimento | `learning.py` | etichette a 72h (spike GDELT ≥ 2σ o Threat Board +8); logistica; promossa solo se AUC ≥ 0,60 su holdout temporale |
| Report | `run_all.py` | `out/iw-report.json`, `out/iw-history.json` |

## Onestà del metodo

- Prime 5 giornate: nessuna baseline → nessun indicatore attivo, il report lo dichiara.
- Fino a 60 giorni-zona etichettati e 10 eventi positivi il punteggio è **solo regola I&W**. Il campo
  `model.mode` vale `rule-based` o `learned`, con `reason_it` che spiega perché.
- L'etichetta è un proxy (notizie di colpi / salto del Threat Board), non "è avvenuto un attacco".
- adsb.lol copre dove ci sono ricevitori: Europa, Golfo, Giappone/Corea bene; Sahel, Sudan, Myanmar,
  Artico poco. Una baseline bassa lì è copertura, non calma.

## Test

```
python tests/test_pipeline.py
```
Memoria sintetica di 40 giorni con un surge piantato: verifica che gli indicatori scattino sul teatro
giusto e non altrove. Non tocca `memory/`.

## Analisi senza raccolta

```
python run_all.py --no-collect
```
