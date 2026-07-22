"""
Generate synthetic RAW datasets for a self-contained demo run of the
multi-agent pipeline. NOT the NDA data — purely fictitious records that
conform to the raw schema so shared/preprocessing.py + FeatureBuilder run
end-to-end without the protected CSVs.

Output: data/raw/ALLARMI.csv, data/raw/TIPOLOGIA_VIAGGIATORE.csv
Run:    python scripts/gen_synthetic_data.py
"""
from __future__ import annotations
import random
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

# ── Airports ────────────────────────────────────────────────────────────────
ARR = ["FCO", "MXP", "LIN", "BLQ", "NAP", "VCE", "BGY", "CTA", "PMO", "TRN", "BRI"]
DEP = ["CMN", "ALG", "SIN", "PVG", "IST", "DXB", "CAI", "TUN", "BEG", "TIA",
       "DKR", "LOS", "GYD", "AMM", "BEY", "DEL", "BKK", "HKG", "JNB", "ACC",
       "TLV", "CASA", "NBO", "ADD", "KRT", "LHR", "CDG", "FRA", "MAD", "ATH"]
COUNTRY = {
    "CMN": ("Marocco", "MAR"), "ALG": ("Algeria", "DZA"), "SIN": ("Singapore", "SGP"),
    "PVG": ("Cina", "CHN"), "IST": ("Turchia", "TUR"), "DXB": ("Emirati", "ARE"),
    "CAI": ("Egitto", "EGY"), "TUN": ("Tunisia", "TUN"), "BEG": ("Serbia", "SRB"),
    "TIA": ("Albania", "ALB"), "DKR": ("Senegal", "SEN"), "LOS": ("Nigeria", "NGA"),
    "GYD": ("Azerbaigian", "AZE"), "AMM": ("Giordania", "JOR"), "BEY": ("Libano", "LBN"),
    "DEL": ("India", "IND"), "BKK": ("Thailandia", "THA"), "HKG": ("Hong Kong", "HKG"),
    "JNB": ("Sudafrica", "ZAF"), "ACC": ("Ghana", "GHA"), "TLV": ("Israele", "ISR"),
    "CASA": ("Marocco", "MAR"), "NBO": ("Kenya", "KEN"), "ADD": ("Etiopia", "ETH"),
    "KRT": ("Sudan", "SDN"), "LHR": ("Regno Unito", "GBR"), "CDG": ("Francia", "FRA"),
    "FRA": ("Germania", "DEU"), "MAD": ("Spagna", "ESP"), "ATH": ("Grecia", "GRC"),
}
ZONE = {d: random.randint(1, 9) for d in DEP}

OCC_TYPES = [
    "Allarmi generati", "Allarmi generati da SDI/NSIS", "Allarmi generati da INTERPOL",
    "Allarmi Chiusi", "Allarmi NON Chiusi", "Allarmi Rilevanti", "Voli con Allarmi",
    "Viaggiatori con Allarmi", "Nulla a procedere SDI", "Nulla a procedere NSIS",
    "Nulla a procedere INT",
]
MOTIVI = ["INTERPOL", "SDI", "NSIS", "TSC", "Manuale"]
ESITI = ["OK", "SEGNALATO", "RESPINTO", "FERMATO", "IN ATTESA"]
GENERI = ["M", "F"]
DOCS = ["Passaporto", "Carta d'identità", "Visto", "Permesso di soggiorno"]
FASCE = ["18-30", "31-45", "46-60", "61+", "0-17"]
AIRLINES = ["AZ", "EK", "TK", "AF", "LH", "QR", "MS", "SV"]
MONTHS = [1, 2]

def rand_date(month):
    day = random.randint(1, 27)
    return f"2024-{month:02d}-{day:02d}"

# ── Build routes (dep -> arr) ───────────────────────────────────────────────
routes = []
for dep in DEP:
    for arr in random.sample(ARR, k=random.randint(4, 8)):
        routes.append((dep, arr))
random.shuffle(routes)
routes = routes[:220]

# mark ~12% as anomalous "hot" routes
hot = set(random.sample(range(len(routes)), k=int(len(routes) * 0.12)))

allarmi_rows = []
viagg_rows = []

for i, (dep, arr) in enumerate(routes):
    paese, iso3 = COUNTRY.get(dep, ("Altro", "OTH"))
    zona = ZONE[dep]
    is_hot = i in hot
    n_months = random.randint(1, 2)

    # ---- ALLARMI rows ----
    interpol_bias = 0.55 if is_hot else 0.18
    base_tot = random.randint(400, 1500) if is_hot else random.randint(20, 400)
    for m in random.sample(MONTHS, k=n_months):
        n_occ = random.randint(5, 10)
        for _ in range(n_occ):
            occ = random.choice(OCC_TYPES)
            # hot routes: skew motivo toward INTERPOL, more NON Chiusi (low closure)
            if is_hot and random.random() < interpol_bias:
                motivo = "INTERPOL"
            else:
                motivo = random.choices(MOTIVI, weights=[2, 3, 2, 1, 1])[0]
            if is_hot and occ == "Allarmi Chiusi" and random.random() < 0.7:
                occ = "Allarmi NON Chiusi"
            tot = max(1, int(np.random.poisson(base_tot / n_occ)))
            allarmi_rows.append({
                "AREOPORTO_ARRIVO": arr, "AREOPORTO_PARTENZA": dep,
                "ANNO_PARTENZA": 2024, "MESE_PARTENZA": m, "DATA_PARTENZA": rand_date(m),
                "TOT": tot, "ZONA": zona, "OCCORRENZE": occ, "MOTIVO_ALLARME": motivo,
                "PAESE_PART": paese, "PAESE_ARR": "Italia",
                "CODICE_PAESE_PART": iso3, "CODICE_PAESE_ARR": "ITA",
                # decoy columns that preprocessing drops
                "Paese Partenza": paese, "tot voli": random.randint(1, 50),
            })

    # ---- VIAGGIATORI rows ----
    reject_bias = 0.30 if is_hot else 0.06
    alarm_bias = 0.55 if is_hot else 0.12
    for m in random.sample(MONTHS, k=n_months):
        n_prof = random.randint(5, 10)
        for _ in range(n_prof):
            entrati = random.randint(50, 900)
            allarmati = int(entrati * min(1.0, abs(np.random.normal(alarm_bias, 0.1))))
            investigati = int(min(entrati, allarmati * random.uniform(0.4, 1.0)))
            esito = random.choices(
                ESITI,
                weights=[6, 2, 4, 2, 1] if is_hot else [12, 2, 1, 1, 1],
            )[0]
            viagg_rows.append({
                "AREOPORTO_ARRIVO": arr, "AREOPORTO_PARTENZA": dep,
                "ANNO_PARTENZA": 2024, "MESE_PARTENZA": m, "DATA_PARTENZA": rand_date(m),
                "ENTRATI": entrati, "ALLARMATI": allarmati, "INVESTIGATI": investigati,
                "GENERE": random.choice(GENERI), "TIPO_DOCUMENTO": random.choice(DOCS),
                "FASCIA_ETA": random.choice(FASCE), "ZONA": zona,
                "NAZIONALITA": iso3, "ESITO_CONTROLLO": esito,
                "COMPAGNIA_AEREA": random.choice(AIRLINES),
                "PAESE_PART": paese, "PAESE_ARR": "Italia",
                "CODICE_PAESE_PART": iso3, "CODICE_PAESE_ARR": "ITA",
                # decoy columns that preprocessing drops
                "num volo": random.randint(100, 9999), "FASCIA ETA": random.choice(FASCE),
            })

df_a = pd.DataFrame(allarmi_rows)
df_v = pd.DataFrame(viagg_rows)
df_a.to_csv(RAW / "ALLARMI.csv", index=False)
df_v.to_csv(RAW / "TIPOLOGIA_VIAGGIATORE.csv", index=False)

print(f"routes: {len(routes)} (hot: {len(hot)})")
print(f"ALLARMI.csv: {df_a.shape}")
print(f"TIPOLOGIA_VIAGGIATORE.csv: {df_v.shape}")
