"""Pipeline a due modelli per il prezzo a N anni di un appartamento ad Andora.

MODELLO MICRO (Random Forest) - valore di mercato OGGI dai servizi della casa,
  con baseline OMI B3 come feature di ancoraggio di zona.
MODELLO MACRO (forecasting) - proiezione dell'indice ISTAT dei prezzi delle
  abitazioni NORD-OVEST. Si stimano DUE modelli e si confrontano in backtest:
    - Prophet (come da traccia)
    - ARIMA (statsmodels) - obbligatorio: su una serie trimestrale corta
      (~44 punti) Prophet e' fragile, ARIMA e' il controllo di robustezza.
INFERENZA - predict_future_price(features, anni): prezzo RF di oggi x
  coefficiente di rivalutazione atteso dal modello macro scelto.

Nota onesta: il coefficiente macro descrive il TREND DI ZONA (Nord-ovest), non
la singola casa. Una previsione puntuale a 5 anni per un immobile non e'
affidabile: l'output e' una forbice, da leggere come ordine di grandezza.
"""

import contextlib
import io
import logging
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import KFold, cross_val_predict

from data_fetcher import (CLASSE_ORD, fetch_istat_ipab, load_omi_b3,
                          simulate_micro_dataset)

warnings.filterwarnings("ignore")
for _n in ("cmdstanpy", "prophet"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

# Feature del modello micro (ordine fissato).
MICRO_FEATURES = ["metratura", "piano", "ascensore", "classe_energetica_ord",
                  "stato_conservazione", "distanza_mare_km", "box_auto",
                  "valore_zona_eur_mq"]
RF_PARAMS = dict(n_estimators=120, max_depth=9, min_samples_leaf=4,
                 random_state=0, n_jobs=-1)


# =========================================================================== #
#  MODELLO MICRO
# =========================================================================== #
def _prepara_micro():
    df = simulate_micro_dataset(salva=False)
    omi = load_omi_b3().rename(columns={"stato": "stato_conservazione"})
    df = df.merge(omi[["stato_conservazione", "eur_mq_mid"]],
                  on="stato_conservazione", how="left")
    df = df.rename(columns={"eur_mq_mid": "valore_zona_eur_mq"})
    df["classe_energetica_ord"] = df["classe_energetica"].map(CLASSE_ORD)
    return df


def train_micro(verbose=True):
    df = _prepara_micro()
    X = df[MICRO_FEATURES].astype(float)
    y = df["prezzo_vendita_eur"].astype(float)

    cv = KFold(5, shuffle=True, random_state=0)
    oof = cross_val_predict(RandomForestRegressor(**RF_PARAMS), X, y, cv=cv)
    mae = mean_absolute_error(y, oof)
    rmse = float(np.sqrt(mean_squared_error(y, oof)))
    model = RandomForestRegressor(**RF_PARAMS).fit(X, y)

    if verbose:
        print("── MODELLO MICRO (Random Forest) ─────────────────────────────")
        print(f"  compravendite: {len(df)} | MAE {mae:,.0f} € | RMSE {rmse:,.0f} €")
        imp = sorted(zip(MICRO_FEATURES, model.feature_importances_),
                     key=lambda t: -t[1])
        print("  importanza:", ", ".join(f"{n} {v:.0%}" for n, v in imp[:4]))
    return model, dict(mae=mae, rmse=rmse)


def _valore_zona(stato):
    omi = load_omi_b3()
    return float(omi.loc[omi["stato"] == stato, "eur_mq_mid"].iloc[0])


def predict_price_today(model, metratura, piano, ascensore, classe_energetica,
                        stato_conservazione, distanza_mare_km, box_auto):
    x = pd.DataFrame([{
        "metratura": metratura, "piano": piano, "ascensore": int(ascensore),
        "classe_energetica_ord": CLASSE_ORD[classe_energetica.upper()],
        "stato_conservazione": stato_conservazione,
        "distanza_mare_km": distanza_mare_km, "box_auto": int(box_auto),
        "valore_zona_eur_mq": _valore_zona(stato_conservazione),
    }])[MICRO_FEATURES].astype(float)
    return float(model.predict(x)[0])


# =========================================================================== #
#  MODELLO MACRO - Prophet e ARIMA
# =========================================================================== #
@contextlib.contextmanager
def _silenzio():
    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
        yield


def forecast_prophet(df_istat, periods=20, yearly=True):
    """Prophet: proietta l'indice per `periods` trimestri. Ritorna (forecast, cagr_info)."""
    from prophet import Prophet
    d = df_istat.rename(columns={"Data": "ds", "Indice_Prezzo": "y"})[["ds", "y"]]
    m = Prophet(yearly_seasonality=yearly, weekly_seasonality=False,
                daily_seasonality=False, interval_width=0.90)
    with _silenzio():
        m.fit(d)
        future = m.make_future_dataframe(periods=periods, freq="QE")
        fc = m.predict(future)
    return fc[["ds", "yhat", "yhat_lower", "yhat_upper"]], m


def forecast_arima(df_istat, periods=20):
    """ARIMA (statsmodels) con selezione ordine via AIC. Ritorna (forecast_df, order, aic)."""
    from statsmodels.tsa.arima.model import ARIMA
    y = df_istat.set_index("Data")["Indice_Prezzo"].astype(float)
    y.index = pd.DatetimeIndex(y.index).to_period("Q")

    # griglia su (p,d,q) e su drift: una serie in trend richiede un termine di
    # deriva, altrimenti ARIMA(0,1,0) proietta piatto e perde ingiustamente.
    best = None
    for p in range(3):
        for q in range(3):
            for trend in (None, "t"):
                try:
                    with _silenzio():
                        res = ARIMA(y, order=(p, 1, q), trend=trend).fit()
                    if best is None or res.aic < best[0]:
                        best = (res.aic, (p, 1, q), trend, res)
                except Exception:
                    continue
    aic, order, trend, res = best
    if trend == "t":
        order = f"{order}+drift"
    pred = res.get_forecast(steps=periods)
    idx = pd.period_range(y.index[-1] + 1, periods=periods, freq="Q")
    ci = pred.conf_int(alpha=0.10)
    fc = pd.DataFrame({
        "ds": idx.to_timestamp(how="end").normalize(),
        "yhat": pred.predicted_mean.to_numpy(),
        "yhat_lower": ci.iloc[:, 0].to_numpy(),
        "yhat_upper": ci.iloc[:, 1].to_numpy(),
    })
    # concatena lo storico osservato per continuita' dei plot
    hist = pd.DataFrame({"ds": df_istat["Data"].to_numpy(),
                         "yhat": y.to_numpy(),
                         "yhat_lower": y.to_numpy(), "yhat_upper": y.to_numpy()})
    return pd.concat([hist, fc], ignore_index=True), order, float(aic)


def _backtest(df_istat, holdout=8):
    """Confronto Prophet vs ARIMA su holdout finale (RMSE, MAPE)."""
    train, test = df_istat.iloc[:-holdout], df_istat.iloc[-holdout:]
    yt = test["Indice_Prezzo"].to_numpy()
    out = {}
    # Prophet
    try:
        fc, _ = forecast_prophet(train, periods=holdout)
        yhat = fc["yhat"].to_numpy()[-holdout:]
        out["prophet"] = dict(rmse=float(np.sqrt(mean_squared_error(yt, yhat))),
                              mape=float(np.mean(np.abs((yt - yhat) / yt))))
    except Exception as e:
        out["prophet"] = dict(rmse=np.inf, mape=np.inf, err=str(e))
    # ARIMA
    try:
        fc, order, _ = forecast_arima(train, periods=holdout)
        yhat = fc["yhat"].to_numpy()[-holdout:]
        out["arima"] = dict(rmse=float(np.sqrt(mean_squared_error(yt, yhat))),
                           mape=float(np.mean(np.abs((yt - yhat) / yt))), order=order)
    except Exception as e:
        out["arima"] = dict(rmse=np.inf, mape=np.inf, err=str(e))
    out["migliore"] = min(("prophet", "arima"), key=lambda k: out[k]["rmse"])
    return out


@dataclass
class MacroForecast:
    modello: str            # "prophet" o "arima" scelto dal backtest
    forecast: pd.DataFrame  # ds, yhat, yhat_lower, yhat_upper
    valore_oggi: float
    orizzonte_anni: int
    backtest: dict

    def _idx_orizzonte(self):
        return len(self.forecast) - 1  # ultimo trimestre proiettato

    def coefficiente(self, kind="yhat") -> float:
        """Coefficiente di rivalutazione atteso all'orizzonte (kind: yhat/lower/upper)."""
        fut = float(self.forecast[kind].iloc[self._idx_orizzonte()])
        return fut / self.valore_oggi - 1

    def cagr(self) -> float:
        return (1 + self.coefficiente()) ** (1 / self.orizzonte_anni) - 1


def build_macro(df_istat, anni=5, verbose=True) -> MacroForecast:
    periods = anni * 4
    bt = _backtest(df_istat, holdout=min(8, len(df_istat) // 4))
    scelto = bt["migliore"]
    if scelto == "prophet":
        fc, _ = forecast_prophet(df_istat, periods=periods)
    else:
        fc, order, aic = forecast_arima(df_istat, periods=periods)
    valore_oggi = float(df_istat["Indice_Prezzo"].iloc[-1])
    mf = MacroForecast(scelto, fc, valore_oggi, anni, bt)

    if verbose:
        print("── MODELLO MACRO (ISTAT IPAB Nord-ovest) ─────────────────────")
        p, a = bt["prophet"], bt["arima"]
        print(f"  backtest holdout: Prophet RMSE {p['rmse']:.2f} / MAPE {p['mape']:.1%}"
              f"  |  ARIMA{a.get('order','')} RMSE {a['rmse']:.2f} / MAPE {a['mape']:.1%}")
        print(f"  modello scelto (RMSE minore): {scelto.upper()}")
        print(f"  indice oggi {valore_oggi:.1f} -> a {anni} anni "
              f"{mf.forecast['yhat'].iloc[-1]:.1f} "
              f"(rivalutazione {mf.coefficiente():+.1%}, CAGR {mf.cagr():+.2%}/anno)")
    return mf


# =========================================================================== #
#  INFERENZA FINALE
# =========================================================================== #
def predict_future_price(micro_model, macro: MacroForecast, features: dict,
                         anni: int = None, micro_mae: float = 0.0) -> dict:
    """Prezzo futuro = prezzo RF di oggi x (1 + rivalutazione macro attesa).

    La forbice combina DUE fonti di incertezza:
      - il valore di oggi e' noto solo a +/- MAE del Random Forest;
      - la rivalutazione a N anni ha la banda del modello macro (CI 90%).
    Cosi' l'intervallo non e' illusoriamente stretto.
    """
    if anni is None:
        anni = macro.orizzonte_anni
    oggi = predict_price_today(micro_model, **features)
    coef = macro.coefficiente("yhat")
    coef_lo = macro.coefficiente("yhat_lower")
    coef_hi = macro.coefficiente("yhat_upper")
    return {
        "prezzo_oggi": oggi,
        "oggi_basso": oggi - micro_mae,
        "oggi_alto": oggi + micro_mae,
        "coeff_rivalutazione": coef,
        "cagr_macro": macro.cagr(),
        "prezzo_futuro_atteso": oggi * (1 + coef),
        "forbice_bassa": (oggi - micro_mae) * (1 + coef_lo),
        "forbice_alta": (oggi + micro_mae) * (1 + coef_hi),
        "orizzonte_anni": anni,
        "modello_macro": macro.modello,
    }


if __name__ == "__main__":
    print("=" * 64)
    print("ANDORA REAL ESTATE - prezzo a 5 anni, Via Aurelia 111 (zona B3)")
    print("=" * 64)
    micro_model, micro_metr = train_micro()
    istat = fetch_istat_ipab()
    macro = build_macro(istat, anni=5)

    civ111 = dict(metratura=85, piano=3, ascensore=1, classe_energetica="D",
                  stato_conservazione=3, distanza_mare_km=0.2, box_auto=1)
    res = predict_future_price(micro_model, macro, civ111, anni=5,
                               micro_mae=micro_metr["mae"])

    print("\n── INFERENZA FINALE ──────────────────────────────────────────")
    print(f"  Immobile: 85 mq, piano 3, ascensore, classe D, stato 3/4, "
          f"0.2 km mare, box")
    print(f"  Prezzo OGGI (Random Forest) : {res['prezzo_oggi']:,.0f} €")
    print(f"  Rivalutazione macro 5 anni  : {res['coeff_rivalutazione']:+.1%} "
          f"(modello {res['modello_macro'].upper()})")
    print(f"  Prezzo atteso a 5 anni      : {res['prezzo_futuro_atteso']:,.0f} €")
    print(f"  Forbice a 5 anni            : {res['forbice_bassa']:,.0f} € – "
          f"{res['forbice_alta']:,.0f} €")
    print("\n  NB: la rivalutazione descrive il TREND di zona (Nord-ovest), non "
          "la\n  singola casa. Previsione puntuale a 5 anni non affidabile: "
          "forbice = ordine di grandezza.")
