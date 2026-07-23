"""Esporta modello micro (alberi RF) + forecast macro in JSON per la dashboard."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_fetcher import CLASSE_ORD, fetch_istat_ipab, load_omi_b3
from model_pipeline import (MICRO_FEATURES, build_macro, forecast_arima,
                            forecast_prophet, train_micro, _prepara_micro,
                            _valore_zona)

OUT = Path(__file__).resolve().parents[1] / "reports" / "dashboard_export.json"


def _trees(model):
    out = []
    for est in model.estimators_:
        t = est.tree_
        out.append({
            "cl": t.children_left.tolist(), "cr": t.children_right.tolist(),
            "f": t.feature.tolist(),
            "t": [round(float(x), 3) for x in t.threshold],
            "v": [int(round(float(x[0][0]))) for x in t.value],
        })
    return out


def _serie(fc, since):
    s = fc[fc["ds"] >= since]
    return [{"t": d.strftime("%Y-%m"), "y": round(float(y), 1),
             "lo": round(float(lo), 1), "hi": round(float(hi), 1)}
            for d, y, lo, hi in zip(s["ds"], s["yhat"], s["yhat_lower"], s["yhat_upper"])]


def main():
    model, metr = train_micro(verbose=False)
    istat = fetch_istat_ipab()
    macro = build_macro(istat, anni=5, verbose=False)

    fc_p, _ = forecast_prophet(istat, periods=20)
    fc_a, order, _ = forecast_arima(istat, periods=20)
    v0 = float(istat["Indice_Prezzo"].iloc[-1])
    last = istat["Data"].max()

    # coefficiente di rivalutazione per orizzonte (dal modello scelto)
    def coef_at(kind, year):
        fut = float(macro.forecast[kind].iloc[len(macro.forecast) - (5 - year) * 4 - 1])
        return round(fut / v0 - 1, 4)

    coef = {str(y): coef_at("yhat", y) for y in range(1, 6)}
    coef_lo = {str(y): coef_at("yhat_lower", y) for y in range(1, 6)}
    coef_hi = {str(y): coef_at("yhat_upper", y) for y in range(1, 6)}

    export = {
        "features": MICRO_FEATURES,
        "classe_ord": CLASSE_ORD,
        "trees": _trees(model),
        "ranges": {"metratura": [35, 140, 1], "piano": [0, 8, 1],
                   "stato_conservazione": [1, 4, 1],
                   "distanza_mare_km": [0.05, 1.2, 0.05]},
        "valore_zona_by_stato": {str(s): round(_valore_zona(s)) for s in (1, 2, 3, 4)},
        "civico111": {"metratura": 85, "piano": 3, "ascensore": 1,
                      "classe_energetica": "D", "stato_conservazione": 3,
                      "distanza_mare_km": 0.2, "box_auto": 1},
        "micro_metrics": {"mae": round(metr["mae"]), "rmse": round(metr["rmse"])},
        "macro": {
            "scelto": macro.modello,
            "order_arima": str(order),
            "backtest": {k: {"rmse": round(macro.backtest[k]["rmse"], 2),
                             "mape": round(macro.backtest[k]["mape"], 4)}
                         for k in ("prophet", "arima")},
            "indice_oggi": round(v0, 1),
            "history": [{"t": d.strftime("%Y-%m"), "y": round(float(y), 1)}
                        for d, y in zip(istat["Data"], istat["Indice_Prezzo"])],
            "prophet": _serie(fc_p, last),
            "arima": _serie(fc_a, last),
            "coef_by_year": coef, "coef_lo_by_year": coef_lo, "coef_hi_by_year": coef_hi,
        },
    }
    OUT.write_text(json.dumps(export, separators=(",", ":")))
    print(f"Esportato {OUT.name} ({OUT.stat().st_size/1024:.0f} KB) · "
          f"macro scelto={macro.modello}, coef 5y={coef['5']:+.1%}")


if __name__ == "__main__":
    main()
