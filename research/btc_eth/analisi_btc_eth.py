#!/usr/bin/env python3
"""Analisi riproducibile BTC vs ETH.

Scarica 365 giorni di prezzi daily da CoinGecko (API pubblica, nessuna chiave)
e calcola: correlazione dei rendimenti log su piu' finestre, performance,
ratio ETH/BTC, volatilita' e percentuale di giorni concordi.
"""

import json
import math
import ssl
import statistics
import urllib.request
from datetime import datetime, timezone

API = "https://api.coingecko.com/api/v3"


def fetch(url: str) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "btc-eth-research/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.loads(r.read())


def daily_prices(coin: str) -> dict:
    data = fetch(f"{API}/coins/{coin}/market_chart?vs_currency=usd&days=365&interval=daily")
    return {
        datetime.fromtimestamp(t / 1000, tz=timezone.utc).date(): p
        for t, p in data["prices"]
    }


def log_returns(xs: list) -> list:
    return [math.log(xs[i + 1] / xs[i]) for i in range(len(xs) - 1)]


def corr(a: list, b: list) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb)


def main() -> None:
    btc, eth = daily_prices("bitcoin"), daily_prices("ethereum")
    days = sorted(set(btc) & set(eth))
    bp = [btc[d] for d in days]
    ep = [eth[d] for d in days]
    rb, re_ = log_returns(bp), log_returns(ep)

    print(f"Periodo: {days[0]} -> {days[-1]} ({len(days)} giorni)")
    print(f"BTC: ${bp[-1]:,.0f}  ETH: ${ep[-1]:,.0f}  ratio ETH/BTC: {ep[-1]/bp[-1]:.5f}\n")

    print("Correlazione rendimenti log giornalieri:")
    for w in (len(rb), 180, 90, 30):
        print(f"  {w:>3} giorni: {corr(rb[-w:], re_[-w:]):.3f}")

    print("\nPerformance:")
    for w, label in ((364, "12 mesi"), (180, "6 mesi"), (90, "3 mesi"), (30, "30 giorni")):
        w = min(w, len(bp) - 1)
        pb = (bp[-1] / bp[-w - 1] - 1) * 100
        pe = (ep[-1] / ep[-w - 1] - 1) * 100
        pr = ((ep[-1] / bp[-1]) / (ep[-w - 1] / bp[-w - 1]) - 1) * 100
        print(f"  {label:>9}: BTC {pb:+6.1f}%  ETH {pe:+6.1f}%  ratio {pr:+6.1f}%")

    print(f"\nDrawdown dal max 12m: BTC {(bp[-1]/max(bp)-1)*100:.1f}%  ETH {(ep[-1]/max(ep)-1)*100:.1f}%")
    print(f"Volatilita' giornaliera 90g: BTC {statistics.stdev(rb[-90:])*100:.2f}%  ETH {statistics.stdev(re_[-90:])*100:.2f}%")

    same = sum(1 for a, b in zip(rb[-90:], re_[-90:]) if a * b > 0)
    print(f"Giorni concordi (ultimi 90): {same}/90 ({same/90*100:.0f}%)")


if __name__ == "__main__":
    main()
