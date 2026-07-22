"""Genera data/compravendite_granulari.csv: compravendite recenti SIMULATE.

Il prompt prevede esplicitamente dati "che simuleremo o importeremo": questo e'
un dataset SINTETICO (seed fisso) calibrato sui livelli reali del litorale di
Andora, con i servizi granulari richiesti:
  metratura, piano, ascensore, classe_energetica, stato_ristrutturazione,
  distanza_mare_km, garage.

A differenza degli annunci (prezzi richiesti), qui i prezzi rappresentano
PREZZI DI VENDITA (come da atti): nessuno sconto trattativa a valle.
Da sostituire con compravendite reali (stesse colonne) quando disponibili.
"""

from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
N = 400

# Zona OMI: B3 litorale/centrale (la stragrande maggioranza) e qualche C1 collina.
# Il civico 111 di Via Aurelia sta in B3, a ridosso del mare.
CLASSI = ["A", "B", "C", "D", "E", "F", "G"]        # A=migliore
CLASSE_ORD = {c: 7 - i for i, c in enumerate(CLASSI)}  # A->7 ... G->1

# Prezzo di vendita "vero" simulato, in eur/mq, a distanza mare ~0, classe D, piano 2.
BASE_EUR_MQ = {1: 2450, 2: 2900, 3: 3450, 4: 4050}   # per stato_ristrutturazione 1-4
EFFETTO_MARE = -520          # eur/mq per km dal mare
EFFETTO_CLASSE = 55          # eur/mq per gradino di classe energetica sopra la D
EFFETTO_PIANO_ALTO = 90      # eur/mq per piano, se c'e' ascensore (vista)
PENALITA_PIANO_NO_ASC = -110 # eur/mq per piano oltre il 1, senza ascensore
PREMIO_ASCENSORE = 0.025
PREMIO_GARAGE = 16000
RUMORE = 0.06

righe = []
for _ in range(N):
    zona = rng.choice(["B3", "C1"], p=[0.82, 0.18])
    if zona == "B3":
        distanza = round(float(rng.uniform(0.05, 0.9)), 2)
    else:
        distanza = round(float(rng.uniform(0.9, 2.6)), 2)

    mq = int(rng.uniform(38, 130))
    piano = int(rng.integers(0, 8))
    stato = int(rng.choice([1, 2, 3, 4], p=[0.15, 0.35, 0.30, 0.20]))
    classe = str(rng.choice(CLASSI, p=[.05, .08, .17, .25, .22, .15, .08]))
    ascensore = int(rng.random() < (0.75 if (mq > 60 or piano >= 3) else 0.4))
    garage = int(rng.random() < 0.38)

    eur_mq = BASE_EUR_MQ[stato]
    eur_mq += EFFETTO_MARE * distanza
    eur_mq += EFFETTO_CLASSE * (CLASSE_ORD[classe] - CLASSE_ORD["D"])
    if ascensore:
        eur_mq += EFFETTO_PIANO_ALTO * max(piano - 1, 0)
    else:
        eur_mq += PENALITA_PIANO_NO_ASC * max(piano - 1, 0)
    eur_mq *= 1 + 0.12 * (80 - mq) / 80 * 0.5    # lieve diseconomia di scala

    prezzo = eur_mq * mq
    prezzo *= 1 + PREMIO_ASCENSORE * ascensore
    prezzo += PREMIO_GARAGE * garage
    prezzo *= 1 + rng.normal(0, RUMORE)
    prezzo = int(round(max(prezzo, 60000), -3))

    righe.append({
        "zona_omi": zona,
        "prezzo_vendita_eur": prezzo,
        "mq": mq,
        "piano": piano,
        "ascensore": ascensore,
        "classe_energetica": classe,
        "stato_ristrutturazione": stato,
        "distanza_mare_km": distanza,
        "garage": garage,
    })

df = pd.DataFrame(righe)
out = Path(__file__).parent / "data" / "compravendite_granulari.csv"
with open(out, "w") as f:
    f.write(
        "# Compravendite SIMULATE (sintetiche, seed=7) - prezzi di VENDITA.\n"
        "# Servizi granulari: mq, piano, ascensore, classe_energetica, stato, distanza mare, garage.\n"
        "# Da sostituire con compravendite reali (stesse colonne). Generato da dataset_granulare.py\n"
    )
    df.to_csv(f, index=False)
print(f"Scritte {len(df)} compravendite simulate in {out}")
print(df.describe(include='all').T[['count', 'mean', 'min', 'max']].round(1))
