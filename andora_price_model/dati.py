"""Caricamento dati e costruzione del training set.

Due fonti, con natura diversa e trattamento esplicito:

1. Quotazioni OMI (Agenzia delle Entrate): riferimento eur/mq da COMPRAVENDITE
   REALI. Le trasformiamo in pseudo-osservazioni di ancoraggio (prezzo =
   eur/mq x mq) con peso maggiore, perche' sono il dato piu' affidabile.

2. Annunci Idealista/Immobiliare.it: prezzi RICHIESTI, sistematicamente piu'
   alti del prezzo di chiusura del 10-20% in questo mercato. Prima di entrare
   nel training set vengono scontati di SCONTO_TRATTATIVA (default 12%,
   centro della forchetta 10-20%): il modello stima cosi' prezzi di VENDITA.
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# Sconto medio richiesto->venduto. Forchetta tipica riportata da Idealista/
# Immobiliare per il mercato ligure di seconde case: 10-20%.
SCONTO_TRATTATIVA = 0.12

FEATURES = ["mq", "mq2", "stato_conservazione", "distanza_mare_km",
            "ascensore", "garage"]

# Dummy di fonte (0=ancora OMI, 1=annuncio): assorbe la differenza di livello
# residua tra compravendite OMI e annunci scontati. Senza questa colonna la
# differenza tra fonti finirebbe scaricata sui coefficienti di ascensore e
# garage (presenti solo negli annunci), distorcendoli. In predizione si usa
# da_annuncio=0: la stima e' ancorata al livello delle compravendite reali.
COL_FONTE = "da_annuncio"

# Tagli su cui campionare le pseudo-osservazioni OMI di ancoraggio
_TAGLI_MQ_OMI = [50, 70, 90, 110]


def carica_omi_quotazioni() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "omi_quotazioni_andora.csv", comment="#")


def carica_omi_storico() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "omi_storico_andora.csv", comment="#")


def carica_annunci() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "annunci_andora.csv", comment="#")


def pseudo_osservazioni_omi(omi: pd.DataFrame) -> pd.DataFrame:
    """Ancore di prezzo dalle quotazioni OMI (valore centrale della forchetta).

    L'OMI non rileva ascensore/garage: le ancore assumono ascensore presente
    per i tagli medio-grandi (>60 mq, edilizia tipica del litorale) e nessun
    garage, cioe' la quotazione descrive il solo appartamento.
    """
    righe = []
    for _, r in omi.iterrows():
        eur_mq = (r["valore_min_eur_mq"] + r["valore_max_eur_mq"]) / 2
        for mq in _TAGLI_MQ_OMI:
            righe.append({
                "fonte": f"OMI-{r['zona_omi']}",
                "prezzo_vendita_eur": eur_mq * mq,
                "mq": mq,
                "stato_conservazione": r["stato_conservazione"],
                "distanza_mare_km": r["distanza_mare_km_tipica"],
                "ascensore": int(mq > 60),
                "garage": 0,
                "peso": 2.0,
            })
    return pd.DataFrame(righe)


def annunci_corretti(annunci: pd.DataFrame,
                     sconto: float = SCONTO_TRATTATIVA) -> pd.DataFrame:
    out = annunci.copy()
    out["prezzo_vendita_eur"] = out["prezzo_richiesto_eur"] * (1 - sconto)
    out["peso"] = 1.0
    return out.drop(columns=["prezzo_richiesto_eur"])


def costruisci_training_set(sconto: float = SCONTO_TRATTATIVA):
    """Ritorna X (con mq^2), y (eur di vendita stimati) e pesi campione."""
    df = pd.concat(
        [pseudo_osservazioni_omi(carica_omi_quotazioni()),
         annunci_corretti(carica_annunci(), sconto)],
        ignore_index=True,
    )
    df["mq2"] = df["mq"] ** 2
    df[COL_FONTE] = (df["peso"] == 1.0).astype(float)
    X = df[FEATURES + [COL_FONTE]].astype(float)
    y = df["prezzo_vendita_eur"].astype(float)
    return X, y, df["peso"].to_numpy(), df


def eur_mq_medio_zona(distanza_mare_km: float) -> float:
    """eur/mq medio OMI della zona pertinente (per la baseline).

    Zona litorale B3 entro ~0.8 km dal mare, altrimenti semicentrale C1.
    Media dei valori centrali su tutti gli stati di conservazione.
    """
    omi = carica_omi_quotazioni()
    zona = "B3" if distanza_mare_km <= 0.8 else "C1"
    sel = omi[omi["zona_omi"] == zona]
    return float(((sel["valore_min_eur_mq"] + sel["valore_max_eur_mq"]) / 2).mean())
