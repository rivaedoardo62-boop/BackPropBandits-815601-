"""PARTE 2 - Proiezione a 3 anni: scenari di crescita composta, NON regressione.

Il valore futuro di una singola casa non si stima in modo puntuale: dipende da
tassi, turismo, offerta locale, stato dell'immobile. Qui applichiamo al valore
di OGGI (Parte 1) tre tassi annui composti ricavati dalla serie storica OMI
della zona:

  - base      : CAGR sull'intero periodo storico disponibile
  - pessimista: il PEGGIOR CAGR triennale osservato nella serie
  - ottimista : il MIGLIOR CAGR triennale osservato nella serie

Il risultato e' una FORBICE, non un numero secco.
"""

from dataclasses import dataclass

import pandas as pd

from dati import carica_omi_storico

ORIZZONTE_ANNI = 3


@dataclass
class Scenari:
    pessimista: float  # tassi annui composti
    base: float
    ottimista: float

    def proietta(self, valore_oggi: float, anni: int = ORIZZONTE_ANNI) -> dict:
        return {
            "pessimista": valore_oggi * (1 + self.pessimista) ** anni,
            "base": valore_oggi * (1 + self.base) ** anni,
            "ottimista": valore_oggi * (1 + self.ottimista) ** anni,
        }


def _cagr(v0: float, v1: float, anni: int) -> float:
    return (v1 / v0) ** (1 / anni) - 1


def scenari_da_storico_omi(finestra_anni: int = 3) -> Scenari:
    st = carica_omi_storico().sort_values("anno").reset_index(drop=True)
    v = st["valore_medio_eur_mq"].to_numpy(dtype=float)
    n = len(st) - 1

    base = _cagr(v[0], v[-1], n)
    cagr_rolling = [
        _cagr(v[i], v[i + finestra_anni], finestra_anni)
        for i in range(len(v) - finestra_anni)
    ]
    return Scenari(pessimista=min(cagr_rolling), base=base,
                   ottimista=max(cagr_rolling))


def stampa_proiezione(valore_oggi: float, banda_bassa: float,
                      banda_alta: float) -> None:
    sc = scenari_da_storico_omi()
    st = carica_omi_storico()
    print("=" * 66)
    print(f"PARTE 2 - Forbice a {ORIZZONTE_ANNI} anni "
          f"(scenari dal trend OMI {st['anno'].min()}-{st['anno'].max()})")
    print("=" * 66)
    print(f"Tassi annui composti: pessimista {sc.pessimista:+.1%}, "
          f"base {sc.base:+.1%}, ottimista {sc.ottimista:+.1%}")

    centro = sc.proietta(valore_oggi)
    print(f"\nSul valore centrale di oggi ({valore_oggi:,.0f} eur):")
    for nome in ("pessimista", "base", "ottimista"):
        print(f"  {nome:<11}: {centro[nome]:>12,.0f} eur")

    # forbice complessiva: banda bassa con scenario peggiore,
    # banda alta con scenario migliore
    lo = banda_bassa * (1 + sc.pessimista) ** ORIZZONTE_ANNI
    hi = banda_alta * (1 + sc.ottimista) ** ORIZZONTE_ANNI
    print(f"\nFORBICE COMPLESSIVA A {ORIZZONTE_ANNI} ANNI: "
          f"{lo:,.0f} - {hi:,.0f} eur")
    print(
        "\nAVVERTENZA: una previsione puntuale a 3 anni per una singola casa\n"
        "NON e' affidabile. La forbice combina l'incertezza del modello di\n"
        "oggi con scenari macro storici della zona: eventi nuovi (tassi,\n"
        "normativa, clima, offerta locale) possono portarla fuori da questo\n"
        "intervallo. Usarla come ordine di grandezza, non come impegno."
    )


if __name__ == "__main__":
    sc = scenari_da_storico_omi()
    print(sc)
    print(sc.proietta(300_000))
