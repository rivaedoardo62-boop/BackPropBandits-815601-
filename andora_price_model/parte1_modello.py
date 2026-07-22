"""PARTE 1 - Valore di mercato OGGI: regressione lineare edonica.

Poche variabili forti: mq, mq^2, stato_conservazione (1-4), distanza_mare_km,
ascensore, garage. Niente numero di locali (quasi collineare con la metratura).

Validazione con k-fold CV (dataset piccolo), metriche in euro (MAE, MAPE) e
confronto con la baseline "eur/mq medio OMI della zona x mq". L'intervallo di
stima viene dai quantili 10-90% dei residui out-of-fold: e' un intervallo
empirico, non un intervallo di confidenza parametrico.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold

from dati import COL_FONTE, FEATURES, costruisci_training_set, eur_mq_medio_zona

K_FOLD = 5
SEED = 0


@dataclass
class ModelloValoreOggi:
    modello: LinearRegression
    mae_cv: float
    mape_cv: float
    mae_baseline: float
    mape_baseline: float
    residuo_q10: float   # quantili dei residui out-of-fold (eur)
    residuo_q90: float

    def stima(self, mq, stato, distanza_mare_km, ascensore, garage):
        """Ritorna (stima, banda_bassa, banda_alta) in euro."""
        x = pd.DataFrame([{
            "mq": mq, "mq2": mq ** 2, "stato_conservazione": stato,
            "distanza_mare_km": distanza_mare_km,
            "ascensore": int(ascensore), "garage": int(garage),
            COL_FONTE: 0.0,  # predizione sul livello delle compravendite OMI
        }])[FEATURES + [COL_FONTE]].astype(float)
        p = float(self.modello.predict(x)[0])
        return p, p + self.residuo_q10, p + self.residuo_q90


def _cv_out_of_fold(X, y, pesi):
    """Predizioni out-of-fold con k-fold (pesi usati solo nel fit)."""
    oof = np.empty(len(y))
    kf = KFold(n_splits=K_FOLD, shuffle=True, random_state=SEED)
    for train_idx, test_idx in kf.split(X):
        m = LinearRegression()
        m.fit(X.iloc[train_idx], y.iloc[train_idx],
              sample_weight=pesi[train_idx])
        oof[test_idx] = m.predict(X.iloc[test_idx])
    return oof


def addestra(verbose: bool = True) -> ModelloValoreOggi:
    X, y, pesi, df = costruisci_training_set()

    # --- validazione out-of-fold ---
    oof = _cv_out_of_fold(X, y, pesi)
    residui = y.to_numpy() - oof
    mae = float(np.mean(np.abs(residui)))
    mape = float(np.mean(np.abs(residui) / y))

    # baseline: eur/mq medio OMI della zona x mq
    base_pred = np.array([
        eur_mq_medio_zona(d) * m
        for d, m in zip(df["distanza_mare_km"], df["mq"])
    ])
    err_base = y.to_numpy() - base_pred
    mae_base = float(np.mean(np.abs(err_base)))
    mape_base = float(np.mean(np.abs(err_base) / y))

    # --- modello finale su tutti i dati ---
    finale = LinearRegression()
    finale.fit(X, y, sample_weight=pesi)

    esito = ModelloValoreOggi(
        modello=finale,
        mae_cv=mae, mape_cv=mape,
        mae_baseline=mae_base, mape_baseline=mape_base,
        residuo_q10=float(np.quantile(residui, 0.10)),
        residuo_q90=float(np.quantile(residui, 0.90)),
    )

    if verbose:
        n_omi = int((df["peso"] > 1).sum())
        print("=" * 66)
        print("PARTE 1 - Regressione lineare edonica (valore di vendita OGGI)")
        print("=" * 66)
        print(f"Osservazioni: {len(df)} "
              f"({n_omi} ancore OMI, {len(df) - n_omi} annunci scontati del 12%)")
        print(f"\nValidazione {K_FOLD}-fold (out-of-fold):")
        print(f"  MAE  modello  : {mae:>10,.0f} eur")
        print(f"  MAPE modello  : {mape:>10.1%}")
        print(f"  MAE  baseline : {mae_base:>10,.0f} eur   (eur/mq medio zona x mq)")
        print(f"  MAPE baseline : {mape_base:>10.1%}")
        vs = "batte" if mae < mae_base else "NON batte"
        print(f"  -> il modello {vs} la baseline "
              f"({(1 - mae / mae_base):+.0%} di MAE)")
        print("\nCoefficienti (effetti marginali sul prezzo di vendita):")
        for nome, c in zip(FEATURES, finale.coef_):
            print(f"  {nome:<22}{c:>12,.0f} eur")
        print(f"  {'intercetta':<22}{finale.intercept_:>12,.0f} eur")
        c_fonte = finale.coef_[len(FEATURES)]
        print(f"  {COL_FONTE:<22}{c_fonte:>12,.0f} eur  "
              "(scarto residuo annunci-12% vs livello OMI;\n"
              f"  {'':<22}{'':>12}      escluso dalle predizioni)")
        print("  nota: l'effetto della metratura va letto sommando mq e mq^2:")
        c_mq, c_mq2 = finale.coef_[0], finale.coef_[1]
        for m in (50, 80, 110):
            print(f"        a {m} mq il metro marginale vale "
                  f"~{c_mq + 2 * c_mq2 * m:,.0f} eur")
    return esito


if __name__ == "__main__":
    addestra()
