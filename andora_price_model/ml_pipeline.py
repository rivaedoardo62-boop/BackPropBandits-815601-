"""Modello ML (Random Forest) per il prezzo di vendita - Andora, Via Aurelia 111.

Integra due fonti, come richiesto:
  1) Quotazioni OMI (Agenzia delle Entrate): valori min/max eur/mq della zona
     (B3 fascia centrale/litorale) usati come FEATURE DI BASE del valore di zona.
  2) Dataset granulare di compravendite: servizi reali della singola casa
     (mq, piano, ascensore, classe energetica, stato, distanza mare, garage).

Fornisce: merge pandas OMI<->case, preprocessing, training + valutazione
(MAE, RMSE via k-fold), funzione predict_price(), ed export JSON del modello
per la dashboard interattiva.

NB: il dataset granulare e' SIMULATO (vedi dataset_granulare.py). La metodologia
e' reale; sostituendo il CSV con compravendite vere il codice non cambia.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import KFold, cross_val_predict

DATA = Path(__file__).parent / "data"

CLASSE_ORD = {"A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1}

# Feature usate dal modello (ordine fissato: serve anche alla dashboard JS).
FEATURES = [
    "mq", "piano", "ascensore", "classe_energetica_ord",
    "stato_ristrutturazione", "distanza_mare_km", "garage",
    "valore_zona_eur_mq",   # dal merge OMI: ancora di valore della zona
]

RF_PARAMS = dict(n_estimators=120, max_depth=9, min_samples_leaf=4,
                 random_state=0, n_jobs=-1)


# --------------------------------------------------------------------------- #
#  1. MERGE OMI  <->  dataset granulare
# --------------------------------------------------------------------------- #
def carica_omi() -> pd.DataFrame:
    """Valore di zona OMI (eur/mq) per zona e stato: media della forbice min-max."""
    q = pd.read_csv(DATA / "omi_quotazioni_andora.csv", comment="#")
    q["valore_zona_eur_mq"] = (q["valore_min_eur_mq"] + q["valore_max_eur_mq"]) / 2
    return q.rename(columns={"stato_conservazione": "stato_ristrutturazione"})[
        ["zona_omi", "stato_ristrutturazione", "valore_zona_eur_mq",
         "valore_min_eur_mq", "valore_max_eur_mq"]
    ]


def merge_dati() -> pd.DataFrame:
    """Merge tra quotazioni OMI di zona e le singole compravendite."""
    case = pd.read_csv(DATA / "compravendite_granulari.csv", comment="#")
    omi = carica_omi()
    df = case.merge(omi, on=["zona_omi", "stato_ristrutturazione"], how="left")
    df["classe_energetica_ord"] = df["classe_energetica"].map(CLASSE_ORD)
    return df


# --------------------------------------------------------------------------- #
#  2. PREPROCESSING + TRAINING + VALUTAZIONE (MAE, RMSE)
# --------------------------------------------------------------------------- #
def addestra_e_valuta(verbose: bool = True):
    df = merge_dati()
    X = df[FEATURES].astype(float)
    y = df["prezzo_vendita_eur"].astype(float)

    cv = KFold(n_splits=5, shuffle=True, random_state=0)
    oof = cross_val_predict(RandomForestRegressor(**RF_PARAMS), X, y, cv=cv)
    mae = mean_absolute_error(y, oof)
    rmse = float(np.sqrt(mean_squared_error(y, oof)))
    mape = float(np.mean(np.abs((y - oof) / y)))

    # baseline: valore di zona OMI (eur/mq) x mq
    base = df["valore_zona_eur_mq"] * df["mq"]
    mae_base = mean_absolute_error(y, base)
    rmse_base = float(np.sqrt(mean_squared_error(y, base)))

    modello = RandomForestRegressor(**RF_PARAMS).fit(X, y)

    if verbose:
        print("=" * 68)
        print("MODELLO ML - Random Forest sul prezzo di vendita (Andora, B3)")
        print("=" * 68)
        print(f"Compravendite (merge OMI+case): {len(df)}  |  feature: {len(FEATURES)}")
        print("\nValutazione 5-fold (out-of-fold):")
        print(f"  MAE  Random Forest : {mae:>10,.0f} eur")
        print(f"  RMSE Random Forest : {rmse:>10,.0f} eur")
        print(f"  MAPE Random Forest : {mape:>10.1%}")
        print(f"  MAE  baseline OMI  : {mae_base:>10,.0f} eur   (valore zona x mq)")
        print(f"  RMSE baseline OMI  : {rmse_base:>10,.0f} eur")
        print(f"  -> il modello riduce il MAE del {(1 - mae/mae_base):+.0%} vs baseline")
        print("\nImportanza delle feature:")
        for nome, imp in sorted(zip(FEATURES, modello.feature_importances_),
                                key=lambda t: -t[1]):
            print(f"  {nome:<26}{imp:>7.1%}")

    metriche = dict(mae=mae, rmse=rmse, mape=mape,
                    mae_base=mae_base, rmse_base=rmse_base)
    return modello, df, metriche


# --------------------------------------------------------------------------- #
#  3. predict_price()  -  stima per un singolo appartamento
# --------------------------------------------------------------------------- #
def _valore_zona(zona: str, stato: int) -> float:
    omi = carica_omi()
    sel = omi[(omi["zona_omi"] == zona) & (omi["stato_ristrutturazione"] == stato)]
    if sel.empty:
        sel = omi[omi["zona_omi"] == zona]
    return float(sel["valore_zona_eur_mq"].mean())


def predict_price(modello, mq, piano, ascensore, classe_energetica,
                  stato_ristrutturazione, distanza_mare_km, garage,
                  zona="B3") -> float:
    """Prezzo di vendita stimato (eur) per i servizi specifici dell'immobile."""
    x = pd.DataFrame([{
        "mq": mq,
        "piano": piano,
        "ascensore": int(ascensore),
        "classe_energetica_ord": CLASSE_ORD[classe_energetica.upper()],
        "stato_ristrutturazione": stato_ristrutturazione,
        "distanza_mare_km": distanza_mare_km,
        "garage": int(garage),
        "valore_zona_eur_mq": _valore_zona(zona, stato_ristrutturazione),
    }])[FEATURES].astype(float)
    return float(modello.predict(x)[0])


# --------------------------------------------------------------------------- #
#  4. Export JSON del modello per la dashboard interattiva
# --------------------------------------------------------------------------- #
def _scenari_omi():
    st = pd.read_csv(DATA / "omi_storico_andora.csv", comment="#").sort_values("anno")
    v = st["valore_medio_eur_mq"].to_numpy(float)
    n = len(v) - 1
    base = (v[-1] / v[0]) ** (1 / n) - 1
    roll = [(v[i + 3] / v[i]) ** (1 / 3) - 1 for i in range(len(v) - 3)]
    return dict(pess=min(roll), base=base, opt=max(roll))


def esporta_json(modello, df, metriche, percorso: Path):
    """Serializza gli alberi del Random Forest + metadati per la dashboard."""
    alberi = []
    for est in modello.estimators_:
        t = est.tree_
        alberi.append({
            "cl": t.children_left.tolist(),
            "cr": t.children_right.tolist(),
            "f": t.feature.tolist(),
            "t": [round(float(x), 3) for x in t.threshold],
            "v": [int(round(float(x[0][0]))) for x in t.value],
        })
    ranges = {
        "mq": [35, 140, 1], "piano": [0, 8, 1],
        "stato_ristrutturazione": [1, 4, 1],
        "distanza_mare_km": [0.05, 2.6, 0.05],
    }
    export = {
        "features": FEATURES,
        "classe_ord": CLASSE_ORD,
        "trees": alberi,
        "ranges": ranges,
        "importances": {n: round(float(i), 4)
                        for n, i in zip(FEATURES, modello.feature_importances_)},
        "metrics": {k: (round(float(v), 4) if k == "mape" else round(float(v), 1))
                    for k, v in metriche.items()},
        "omi_b3": {"min": 2300, "max": 5200},
        # default: Via Aurelia 111, zona B3, ~0.2 km dal mare
        "civico111": {
            "mq": 85, "piano": 3, "ascensore": 1, "classe_energetica": "D",
            "stato_ristrutturazione": 3, "distanza_mare_km": 0.2, "garage": 1,
            "valore_zona_eur_mq": round(_valore_zona("B3", 3), 0),
        },
        "valore_zona_by_stato": {
            str(s): round(_valore_zona("B3", s), 0) for s in (1, 2, 3, 4)
        },
        "scenari": {k: round(float(v), 4) for k, v in _scenari_omi().items()},
    }
    percorso.write_text(json.dumps(export, separators=(",", ":")))
    return export


if __name__ == "__main__":
    modello, df, metriche = addestra_e_valuta(verbose=True)

    print("\n" + "=" * 68)
    print("predict_price() - Appartamento Via Aurelia 111 (zona B3)")
    print("=" * 68)
    stima = predict_price(modello, mq=85, piano=3, ascensore=1,
                          classe_energetica="D", stato_ristrutturazione=3,
                          distanza_mare_km=0.2, garage=1, zona="B3")
    print(f"  85 mq, piano 3, ascensore, classe D, stato 3/4, 0.2 km mare, garage")
    print(f"  Prezzo di vendita stimato: {stima:,.0f} eur  ({stima/85:,.0f} eur/mq)")

    out = DATA / "modello_export.json"
    esporta_json(modello, df, metriche, out)
    kb = out.stat().st_size / 1024
    print(f"\nModello esportato per la dashboard: {out.name} ({kb:.0f} KB)")
