"""Aggiorna data/annunci_andora.csv scaricando annunci reali dall'API Idealista.

Uso:
  export IDEALISTA_API_KEY=...  IDEALISTA_SECRET=...
  python aggiorna_dati_idealista.py

Senza credenziali stampa le istruzioni ed esce senza toccare il CSV, cosi' la
pipeline continua a girare sui dati illustrativi.
"""

import sys
from pathlib import Path

from idealista_api import CredenzialiMancanti, scarica_annunci, scrivi_csv

CSV = Path(__file__).parent / "data" / "annunci_andora.csv"


def main() -> int:
    try:
        df = scarica_annunci()
    except CredenzialiMancanti as e:
        print(f"[salto] {e}")
        print("La pipeline restera' sui dati illustrativi in", CSV.name)
        return 0
    except Exception as e:  # rete/proxy/API: non sovrascrivere dati validi
        print(f"[errore] chiamata API fallita: {e}", file=sys.stderr)
        return 1

    scrivi_csv(df, CSV)
    print(f"Scritti {len(df)} annunci reali Idealista in {CSV}")
    print(df.describe(numeric_only=True).round(1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
