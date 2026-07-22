"""Genera data/annunci_andora.csv: annunci ILLUSTRATIVI (prezzi RICHIESTI).

Questi NON sono annunci reali: sono dati sintetici calibrati sui livelli di
prezzo osservati sui portali per Andora nel 2025-26 (media annunci
~3.300-3.900 eur/mq vicino al mare, ~2.100-2.700 eur/mq in collina).
Servono solo a rendere lo script eseguibile end-to-end: vanno SOSTITUITI
con annunci veri raccolti da Idealista/Immobiliare.it (stessi nomi colonna).

Deterministico (seed fisso): rieseguirlo produce lo stesso CSV.
"""

from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N = 90

# Prezzo RICHIESTO al mq per stato di conservazione, a distanza mare ~0 km.
# Include gia' il premio del venditore rispetto al prezzo di chiusura.
BASE_EUR_MQ_RICHIESTO = {1: 2500, 2: 2950, 3: 3400, 4: 3950}
EFFETTO_DISTANZA_EUR_MQ_KM = -450  # calo del eur/mq per km dal mare
PREMIO_ASCENSORE = 0.03            # +3% sul prezzo
PREMIO_GARAGE_EUR = 15000          # posto auto/garage venduto col piano casa
RUMORE_PCT = 0.07

righe = []
for i in range(N):
    mq = int(rng.uniform(40, 120))
    stato = int(rng.choice([1, 2, 3, 4], p=[0.15, 0.35, 0.30, 0.20]))
    distanza = round(float(rng.choice([rng.uniform(0.05, 0.5),
                                       rng.uniform(0.5, 1.2),
                                       rng.uniform(1.2, 2.5)],
                                      p=[0.5, 0.3, 0.2])), 2)
    ascensore = int(rng.random() < (0.7 if mq > 60 else 0.45))
    garage = int(rng.random() < 0.4)

    eur_mq = BASE_EUR_MQ_RICHIESTO[stato] + EFFETTO_DISTANZA_EUR_MQ_KM * distanza
    # lieve diseconomia di scala: i tagli piccoli spuntano eur/mq piu' alti
    eur_mq *= 1 + 0.15 * (80 - mq) / 80 * 0.5
    prezzo = eur_mq * mq
    prezzo *= 1 + PREMIO_ASCENSORE * ascensore
    prezzo += PREMIO_GARAGE_EUR * garage
    prezzo *= 1 + rng.normal(0, RUMORE_PCT)
    prezzo = int(round(prezzo, -3))  # arrotondato al migliaio, come i veri annunci

    righe.append({
        "fonte": rng.choice(["idealista", "immobiliare.it"]),
        "prezzo_richiesto_eur": prezzo,
        "mq": mq,
        "stato_conservazione": stato,
        "distanza_mare_km": distanza,
        "ascensore": ascensore,
        "garage": garage,
    })

df = pd.DataFrame(righe)
out = Path(__file__).parent / "data" / "annunci_andora.csv"
with open(out, "w") as f:
    f.write(
        "# Annunci ILLUSTRATIVI (sintetici, seed=42) - prezzi RICHIESTI, non di vendita.\n"
        "# Da sostituire con annunci reali Idealista/Immobiliare.it con le stesse colonne.\n"
        "# Generato da genera_annunci_esempio.py\n"
    )
    df.to_csv(f, index=False)
print(f"Scritti {len(df)} annunci in {out}")
print(df.describe().round(1))
