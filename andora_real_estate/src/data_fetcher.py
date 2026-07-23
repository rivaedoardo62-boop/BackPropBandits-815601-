"""Raccolta dati per il progetto Andora Real Estate.

Tre fonti, con natura diversa e trattamento esplicito:

  1. MACRO - Indice ISTAT dei prezzi delle abitazioni (IPAB), scaricato via API
     REST SDMX filtrando la macro-area NORD-OVEST (REF_AREA=ITC). Questa e' la
     correzione metodologica chiave: l'indice NAZIONALE non descrive una
     localita' turistica ligure, quindi si usa il livello territoriale piu' fine
     realmente pubblicato per l'IPAB (le macro-aree NUTS-1; la singola regione
     Liguria non e' esposta nel dataflow IPAB).

  2. BASELINE di zona - quotazioni OMI (Agenzia delle Entrate) zona B3 di Andora.

  3. MICRO - dataset di compravendite con i servizi della singola casa
     (metratura, piano, ascensore, classe_energetica, distanza_mare, box_auto):
     SIMULATO (seed fisso) ma ancorato ai livelli reali OMI B3.

L'API ISTAT (esploradati.istat.it) richiede uno User-Agent da browser; il vecchio
host sdmx.istat.it e' bloccato. In caso di rete non disponibile si ricade sul CSV
gia' scaricato in data/raw (dato reale messo in cache).
"""

from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

# --- API ISTAT SDMX (IPAB, base 2015=100, abitazioni totali, Nord-ovest) ---
ISTAT_BASE = "https://esploradati.istat.it/SDMXWS/rest"
ISTAT_FLOW = "IT1,143_497,1.0"          # dataflow indice prezzi abitazioni
# chiave = FREQ.REF_AREA.DATA_TYPE.MEASURE.PURCHASES_DWELLINGS
#   Q=trimestrale, ITC=Nord-ovest, 59=indice base 2015=100, 4=numero indice, ALL=tutte
ISTAT_KEY = "Q.ITC.59.4.ALL"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_CA = "/root/.ccr/ca-bundle.crt"
_VERIFY = _CA if Path(_CA).exists() else True

RAW_ISTAT = RAW / "istat_ipab_nordovest.csv"


def _quarter_end(q: str) -> str:
    y, qq = q.split("-Q")
    return f"{y}-{ {'1':'03-31','2':'06-30','3':'09-30','4':'12-31'}[qq] }"


def fetch_istat_ipab(area: str = "ITC", start: str = "2015-Q1",
                     use_cache_on_fail: bool = True) -> pd.DataFrame:
    """Serie storica IPAB (Nord-ovest) via SDMX REST. Ritorna Data, Trimestre, Indice_Prezzo.

    Salva/aggiorna la cache in data/raw. Su errore di rete ricade sulla cache.
    """
    key = ISTAT_KEY.replace("ITC", area)
    url = f"{ISTAT_BASE}/data/{ISTAT_FLOW}/{key}?startPeriod={start}"
    try:
        r = requests.get(url, headers={"User-Agent": _UA,
                         "Accept": "application/vnd.sdmx.data+csv"},
                         timeout=60, verify=_VERIFY)
        r.raise_for_status()
        raw = pd.read_csv(StringIO(r.text))
        s = (raw[["TIME_PERIOD", "OBS_VALUE"]]
             .rename(columns={"TIME_PERIOD": "Trimestre", "OBS_VALUE": "Indice_Prezzo"})
             .sort_values("Trimestre"))
        s["Data"] = pd.to_datetime(s["Trimestre"].map(_quarter_end))
        s = s[["Data", "Trimestre", "Indice_Prezzo"]].reset_index(drop=True)
        _salva_cache_istat(s)
        print(f"[ISTAT] scaricate {len(s)} osservazioni reali (area={area}).")
        return s
    except Exception as e:
        if use_cache_on_fail and RAW_ISTAT.exists():
            print(f"[ISTAT] API non raggiungibile ({e}); uso la cache {RAW_ISTAT.name}.")
            df = pd.read_csv(RAW_ISTAT, comment="#")
            df["Data"] = pd.to_datetime(df["Data"])
            return df
        raise


def _salva_cache_istat(s: pd.DataFrame):
    with open(RAW_ISTAT, "w") as f:
        f.write("# ISTAT - Indice prezzi abitazioni (IPAB), base 2015=100, abitazioni totali.\n")
        f.write("# Macro-area NORD-OVEST (REF_AREA=ITC). Dataflow SDMX IT1,143_497,1.0 (Q.ITC.59.4.ALL).\n")
        f.write("# Fonte REALE: esploradati.istat.it/SDMXWS/rest. Ri-scaricabile con fetch_istat_ipab().\n")
        s.to_csv(f, index=False)


def load_omi_b3() -> pd.DataFrame:
    """Quotazioni OMI zona B3 Andora, con valore centrale eur/mq per stato."""
    q = pd.read_csv(RAW / "omi_b3_andora.csv", comment="#")
    q["eur_mq_mid"] = (q["eur_mq_min"] + q["eur_mq_max"]) / 2
    return q


# --------------------------------------------------------------------------- #
#  MICRO - dataset di compravendite simulate (servizi granulari)
# --------------------------------------------------------------------------- #
CLASSI = ["A", "B", "C", "D", "E", "F", "G"]
CLASSE_ORD = {c: 7 - i for i, c in enumerate(CLASSI)}


def simulate_micro_dataset(n: int = 400, seed: int = 7,
                           salva: bool = True) -> pd.DataFrame:
    """Compravendite SIMULATE in zona B3, ancorate ai livelli OMI reali."""
    rng = np.random.default_rng(seed)
    omi = load_omi_b3().set_index("stato")["eur_mq_mid"].to_dict()
    righe = []
    for _ in range(n):
        distanza = round(float(rng.uniform(0.05, 1.2)), 2)   # zona B3 = litorale
        mq = int(rng.uniform(38, 130))
        piano = int(rng.integers(0, 8))
        stato = int(rng.choice([1, 2, 3, 4], p=[.15, .35, .30, .20]))
        classe = str(rng.choice(CLASSI, p=[.05, .08, .17, .25, .22, .15, .08]))
        ascensore = int(rng.random() < (0.75 if (mq > 60 or piano >= 3) else 0.4))
        box_auto = int(rng.random() < 0.38)

        eur_mq = omi[stato]                                   # ancora OMI reale
        eur_mq += -520 * distanza
        eur_mq += 55 * (CLASSE_ORD[classe] - CLASSE_ORD["D"])
        eur_mq += (90 if ascensore else -110) * max(piano - 1, 0)
        eur_mq *= 1 + 0.12 * (80 - mq) / 80 * 0.5
        prezzo = eur_mq * mq
        prezzo *= 1 + 0.025 * ascensore
        prezzo += 16000 * box_auto
        prezzo *= 1 + rng.normal(0, 0.06)
        righe.append({
            "prezzo_vendita_eur": int(round(max(prezzo, 60000), -3)),
            "metratura": mq, "piano": piano, "ascensore": ascensore,
            "classe_energetica": classe, "stato_conservazione": stato,
            "distanza_mare_km": distanza, "box_auto": box_auto,
        })
    df = pd.DataFrame(righe)
    if salva:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        out = PROCESSED / "compravendite_andora.csv"
        with open(out, "w") as f:
            f.write("# Compravendite SIMULATE (seed=7) zona B3 Andora, prezzi di VENDITA,\n")
            f.write("# ancorate ai valori OMI reali. Da sostituire con atti reali (stesse colonne).\n")
            df.to_csv(f, index=False)
    return df


if __name__ == "__main__":
    print("== MACRO: ISTAT IPAB Nord-ovest ==")
    istat = fetch_istat_ipab()
    print(istat.tail(3).to_string(index=False))
    print("\n== BASELINE: OMI B3 Andora ==")
    print(load_omi_b3().to_string(index=False))
    print("\n== MICRO: compravendite simulate ==")
    micro = simulate_micro_dataset()
    print(micro.head(3).to_string(index=False))
    print(f"... {len(micro)} righe salvate in data/processed/")
