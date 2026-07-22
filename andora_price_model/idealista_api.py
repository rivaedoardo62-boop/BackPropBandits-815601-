"""Client dell'API ufficiale Idealista per raccogliere annunci reali ad Andora.

IMPORTANTE - l'API Idealista NON e' liberamente pubblica: richiede una coppia
apikey/secret da richiedere e far approvare su
https://developers.idealista.com/access-request (flusso OAuth2
client_credentials, tier gratuito ~100 richieste/mese). Immobiliare.it non
espone un'API pubblica di ricerca (solo import annunci per agenzie e il
prodotto a pagamento "Insights"), quindi qui integriamo solo Idealista.

Credenziali lette da variabili d'ambiente (mai committare chiavi):
  IDEALISTA_API_KEY, IDEALISTA_SECRET

Gli annunci Idealista sono prezzi RICHIESTI: restituiamo le stesse colonne del
CSV illustrativo (fonte, prezzo_richiesto_eur, mq, stato_conservazione,
distanza_mare_km, ascensore, garage), cosi' il resto della pipeline non cambia.
Lo sconto richiesto->venduto resta applicato a valle in dati.py.
"""

import base64
import math
import os
from pathlib import Path

import pandas as pd
import requests

OAUTH_URL = "https://api.idealista.com/oauth/token"
SEARCH_URL = "https://api.idealista.com/3.5/it/search"

# Centro di Andora (SV) e raggio di ricerca (metri).
ANDORA_LAT, ANDORA_LON = 43.9497, 8.1417
RAGGIO_METRI = 3000

# Punti sulla battigia di Andora: la distanza dal mare e' la minima distanza
# di ogni annuncio da questi punti (approssimazione, l'API non fornisce il dato).
COSTA_ANDORA = [
    (43.9455, 8.1360),  # zona ponente / Marina
    (43.9440, 8.1470),  # centro litorale, Via Aurelia
    (43.9430, 8.1580),  # zona levante / Rollo
]

# L'API espone status in 3 livelli: li mappiamo sulla scala 1-4 del modello.
# "da ristrutturare" pieno (1) non e' distinguibile via API: renew -> 2.
MAP_STATUS = {"renew": 2, "good": 3, "newdevelopment": 4}

# CA bundle del proxy dell'ambiente (se presente), altrimenti verifica standard.
_CA = os.environ.get("REQUESTS_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
_VERIFY = _CA if Path(_CA).exists() else True


class CredenzialiMancanti(RuntimeError):
    pass


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distanza_mare_km(lat, lon) -> float:
    return round(min(_haversine_km(lat, lon, cy, cx) for cy, cx in COSTA_ANDORA), 2)


def _ottieni_token(api_key: str, secret: str) -> str:
    cred = base64.b64encode(f"{api_key}:{secret}".encode()).decode()
    r = requests.post(
        OAUTH_URL,
        headers={"Authorization": f"Basic {cred}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "read"},
        timeout=30, verify=_VERIFY,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _mappa_elemento(el: dict) -> dict | None:
    """Traduce un elemento della risposta Idealista nelle nostre colonne."""
    stato = MAP_STATUS.get(el.get("status", ""))
    if stato is None or "size" not in el or "price" not in el:
        return None
    lat, lon = el.get("latitude"), el.get("longitude")
    dist = distanza_mare_km(lat, lon) if lat and lon else None
    parcheggio = el.get("parkingSpace") or {}
    return {
        "fonte": "idealista",
        "prezzo_richiesto_eur": int(round(float(el["price"]), -3)),
        "mq": int(round(float(el["size"]))),
        "stato_conservazione": stato,
        "distanza_mare_km": dist,
        "ascensore": int(bool(el.get("hasLift", False))),
        "garage": int(bool(parcheggio.get("hasParkingSpace", False))),
    }


def scarica_annunci(max_items: int = 50, max_pagine: int = 3) -> pd.DataFrame:
    """Scarica annunci di vendita di appartamenti attorno ad Andora.

    Solleva CredenzialiMancanti se non sono impostate IDEALISTA_API_KEY/SECRET.
    """
    api_key = os.environ.get("IDEALISTA_API_KEY")
    secret = os.environ.get("IDEALISTA_SECRET")
    if not api_key or not secret:
        raise CredenzialiMancanti(
            "Imposta IDEALISTA_API_KEY e IDEALISTA_SECRET (richiedi l'accesso su "
            "https://developers.idealista.com/access-request)."
        )

    token = _ottieni_token(api_key, secret)
    righe = []
    for pagina in range(1, max_pagine + 1):
        r = requests.post(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "operation": "sale",
                "propertyType": "homes",
                "center": f"{ANDORA_LAT},{ANDORA_LON}",
                "distance": RAGGIO_METRI,
                "maxItems": max_items,
                "numPage": pagina,
                "locale": "it",
                "order": "distance",
                "sort": "asc",
            },
            timeout=60, verify=_VERIFY,
        )
        r.raise_for_status()
        body = r.json()
        elementi = body.get("elementList", [])
        for el in elementi:
            m = _mappa_elemento(el)
            if m and m["distanza_mare_km"] is not None:
                righe.append(m)
        if pagina >= int(body.get("totalPages", pagina)):
            break

    df = pd.DataFrame(righe).drop_duplicates()
    if df.empty:
        raise RuntimeError("Nessun annuncio utilizzabile restituito dall'API.")
    return df


def scrivi_csv(df: pd.DataFrame, percorso: Path) -> None:
    with open(percorso, "w") as f:
        f.write(
            "# Annunci REALI da API Idealista (prezzi RICHIESTI, non di vendita).\n"
            "# Generato da idealista_api.py / aggiorna_dati_idealista.py\n"
            "# stato_conservazione mappato da status Idealista: renew=2, good=3, newdevelopment=4.\n"
            "# distanza_mare_km stimata da lat/lon vs battigia di Andora (approssimazione).\n"
        )
        df.to_csv(f, index=False)
