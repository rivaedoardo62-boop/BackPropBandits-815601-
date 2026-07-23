"""Genera il grafico di confronto delle previsioni macro (Prophet vs ARIMA).

Salva reports/forecast_nordovest.png: storico ISTAT Nord-ovest + proiezioni a
5 anni dei due modelli con bande di incertezza. Serve al notebook 03 e al README.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_fetcher import fetch_istat_ipab
from model_pipeline import build_macro, forecast_arima, forecast_prophet

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)

TEAL, CORAL, INK, GRID = "#0E7C86", "#C25A4E", "#25403D", "#DCE6E4"


def main():
    istat = fetch_istat_ipab()
    anni, periods = 5, 20
    macro = build_macro(istat, anni=anni, verbose=False)
    fc_p, _ = forecast_prophet(istat, periods=periods)
    fc_a, order, _ = forecast_arima(istat, periods=periods)

    fig, ax = plt.subplots(figsize=(10, 5.4), dpi=130)
    ax.plot(istat["Data"], istat["Indice_Prezzo"], color=INK, lw=2.2,
            label="ISTAT IPAB Nord-ovest (reale)", zorder=5)

    fp = fc_p[fc_p["ds"] > istat["Data"].max()]
    ax.plot(fp["ds"], fp["yhat"], color=TEAL, lw=2, label="Prophet (previsione 5 anni)")
    ax.fill_between(fp["ds"], fp["yhat_lower"], fp["yhat_upper"],
                    color=TEAL, alpha=0.15)

    fa = fc_a[fc_a["ds"] > istat["Data"].max()]
    ax.plot(fa["ds"], fa["yhat"], color=CORAL, lw=2, ls="--",
            label=f"ARIMA{order} (controllo robustezza)")
    ax.fill_between(fa["ds"], fa["yhat_lower"], fa["yhat_upper"],
                    color=CORAL, alpha=0.10)

    ax.axvline(istat["Data"].max(), color="#9AB0AD", lw=1, ls=":")
    scelto = macro.modello.upper()
    ax.set_title(f"Indice prezzi abitazioni — Nord-ovest · proiezione 5 anni\n"
                 f"modello scelto dal backtest: {scelto}", fontsize=12,
                 color=INK, fontweight="bold")
    ax.set_xlabel("Anno"); ax.set_ylabel("Indice IPAB (base 2015 = 100)")
    ax.grid(True, color=GRID, lw=.8); ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    fig.tight_layout()
    path = OUT / "forecast_nordovest.png"
    fig.savefig(path, bbox_inches="tight")
    print("Salvato", path)


if __name__ == "__main__":
    main()
