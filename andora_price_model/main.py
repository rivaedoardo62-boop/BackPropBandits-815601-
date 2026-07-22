"""Stima del prezzo di un appartamento ad Andora (SV), zona litorale/Via Aurelia.

Uso:
  python main.py --mq 75 --stato 3 --distanza-mare 0.2 --ascensore --garage

Output: valore di vendita stimato OGGI (con intervallo empirico) + forbice a
3 anni in tre scenari (pessimista/base/ottimista) dal trend storico OMI.
"""

import argparse

from parte1_modello import addestra
from parte2_proiezione import stampa_proiezione


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mq", type=float, required=True, help="superficie in mq")
    p.add_argument("--stato", type=int, required=True, choices=[1, 2, 3, 4],
                   help="1=da ristrutturare, 2=abitabile, 3=buono, 4=ristrutturato")
    p.add_argument("--distanza-mare", type=float, required=True,
                   help="distanza dal mare in km")
    p.add_argument("--ascensore", action="store_true")
    p.add_argument("--garage", action="store_true")
    args = p.parse_args()

    modello = addestra(verbose=True)
    stima, lo, hi = modello.stima(args.mq, args.stato, args.distanza_mare,
                                  args.ascensore, args.garage)

    print()
    print("=" * 66)
    print("VALORE DI VENDITA STIMATO OGGI")
    print("=" * 66)
    print(f"Immobile: {args.mq:.0f} mq, stato {args.stato}/4, "
          f"{args.distanza_mare:.2f} km dal mare, "
          f"ascensore={'si' if args.ascensore else 'no'}, "
          f"garage={'si' if args.garage else 'no'}")
    print(f"  Stima centrale : {stima:>12,.0f} eur  ({stima / args.mq:,.0f} eur/mq)")
    print(f"  Intervallo     : {lo:>12,.0f} - {hi:,.0f} eur "
          f"(quantili 10-90% dei residui out-of-fold)")
    print("  Nota: gli annunci usati nel training sono prezzi RICHIESTI,\n"
          "  scontati del 12% (forchetta tipica 10-20%): la stima e' un\n"
          "  prezzo di CHIUSURA atteso, non un prezzo da vetrina.")
    print()
    stampa_proiezione(stima, lo, hi)


if __name__ == "__main__":
    main()
