# Ricerca BTC vs ETH — "È la fine di Bitcoin e l'ascesa di Ethereum?"

**Data analisi: 14 luglio 2026** · Dati live da CoinGecko API, mempool.space API, fonti stampa verificate.
Fonte teorica PoW/PoS: study guide "Data Privacy & Security" (sez. 2.7–2.8, Blockchains/Consensus/Ethereum).

> Questo documento è ricerca, non consulenza finanziaria.

---

## 1. Fotografia del mercato (14 lug 2026, CoinGecko)

| Metrica | BTC | ETH |
|---|---|---|
| Prezzo | $63.636 | $1.862 |
| Market cap | $1.276 T | $224,8 B |
| Dominance | 56,0 % | 9,9 % |
| Max 12 mesi | $124.774 | $4.829 |
| Drawdown dal max | **−49,0 %** | **−61,4 %** |
| Perf. 12 mesi | −46,9 % | −38,2 % |
| Perf. 6 mesi | −34,4 % | **−44,5 %** |
| Perf. 30 giorni | −1,2 % | **+10,9 %** |
| Volatilità giornaliera (90g) | 1,81 % | 2,52 % |

Ratio ETH/BTC: 0,02926 (min 12m: 0,02514 · max 12m: 0,04214). Negli ultimi 30 giorni il ratio è risalito del +12,2 %.

## 2. La domanda centrale: BTC ed ETH sono "complementari"?

**No — sono fortemente correlati.** Correlazione dei rendimenti log giornalieri (CoinGecko, chiusure daily):

| Finestra | Correlazione |
|---|---|
| 365 giorni | 0,864 |
| 180 giorni | 0,922 |
| 90 giorni | 0,870 |
| 30 giorni | 0,873 |

Negli ultimi 90 giorni BTC ed ETH hanno chiuso nella **stessa direzione l'87 % dei giorni** (78/90).

Conclusione: l'ipotesi "se BTC scende, ETH può salire" è **falsa come regola giornaliera** (si muovono quasi sempre insieme), ma **vera come tendenza relativa su finestre lunghe**: la *grandezza* dei movimenti diverge (il ratio ETH/BTC ha oscillato ±40 % nell'anno). Non è decorrelazione: è **rotazione dentro una stessa asset class**. Il trade coerente con questa osservazione non è "vendere BTC e sperare", ma il **relative value sul ratio ETH/BTC**.

## 3. Verifica dei claim (dalla chat)

| Claim | Verdetto | Evidenza |
|---|---|---|
| "BlackRock ha venduto 3.671 BTC (~$230M) e comprato 10.566 ETH" | ✅ Vero, ma ridimensionato | Confermato (9 giu 2026, più testate). Nota: ha comprato ~$17,7M di ETH, non $230M — e $230M è ~0,02 % della market cap di BTC. È un ribilanciamento, non una fuga. |
| "Centri di mining smantellati/riconvertiti per l'AI" | ✅ Vero nella sostanza | ~$70B di contratti AI/HPC nel settore mining nel 2025-26 (Hut 8 $9,8B, TeraWulf $12,8B, IREN–Microsoft $9,7B). Causa: redditività mining calata post-halving 2024 + boom domanda AI. Non significa "la blockchain non funziona". |
| "Non si estrae più / la blockchain è vecchia" | ❌ Falso | Hashrate BTC: 924 EH/s oggi vs 900 EH/s 12 mesi fa (mempool.space). È −29 % dal picco di ott 2025 (1.306 EH/s), ma sopra il livello di un anno fa. Il mining continua, la sicurezza della rete resta enorme. |
| "BTC continua a scendere" | ✅ Vero | −49 % dal massimo. Ma nella storia di BTC è normale: 2018 −84 %, 2022 −77 %. Un drawdown del 50 % non è mai stato, finora, "la fine". |
| "Fine di BTC, ascesa di ETH" | ❌ Non supportato dai dati | ETH è messo *peggio* dal suo massimo (−61 % vs −49 %) e ha sottoperformato BTC a 6 mesi. Solo nelle ultime 4-5 settimane ETH sovraperforma. Dominance BTC al 56 %. |
| "ETH/Cardano hanno una tecnologia nuova, proof of stake" | ⚠️ Impreciso | PoS non è nuova: idea del 2012, Ethereum è PoS dal Merge (set 2022). Il vantaggio reale è ~99,95 % di energia in meno e la possibilità di *staking yield* — che nel 2026 è diventato prodotto istituzionale (ETF staked ETH di BlackRock, mar 2026). |

## 4. Perché il mercato scende (contesto 2026)

- **Flussi ETF**: 8 settimane consecutive di deflussi (fine mag–inizio lug 2026), ~$9,46B usciti da ETF BTC+ETH (~$4,2B dai soli ETF BTC); rotazione istituzionale verso equity ETF (che hanno segnato $1T di afflussi nel semestre). Prima settimana positiva: 7–11 lug, +$282M (BTC +$197M, ETH +$84M).
- **Liquidazioni**: picco 2026 ~$1,8B in un giorno (massacro dei long); 14 lug ~$289M in 24h con BTC brevemente sotto $62k su tensioni geopolitiche USA–Iran.
- **Segnale pro-ETH reale**: i flussi ETF ETH pesano ~0,88 % dell'AUM contro ~1/3 di quell'intensità per BTC, e lo staked-ETF rende ETH un asset *a rendimento* dentro un prodotto regolamentato.

## 5. PoW vs PoS (dal PDF, sez. 2.7)

| Aspetto | PoW (Bitcoin) | PoS (Ethereum) |
|---|---|---|
| Fonte di sicurezza | Potenza di calcolo | Stake economico |
| Energia | Molto alta | ~99,95 % in meno |
| Hardware | ASIC | Computer standard |
| Costo attacco 51 % | >50 % hash power | >50 % degli ETH in staking (>$50B) |
| Penalità disonestà | Elettricità sprecata | Slashing dello stake |
| Block time | ~10 min | ~12 s |
| Modello | UTXO, cap 21M, SHA-256 | Account-based, no cap, Keccak-256 |

Implicazione economica: il PoW lega il costo di BTC a energia/hardware (da qui il pivot dei miner verso l'AI quando i margini calano); il PoS lega ETH a un rendimento da staking (da qui l'appeal per la finanza tradizionale via ETF).

## 6. Verdetto sintetico

1. **"Fine di BTC": nessun dato la supporta.** Drawdown ciclico nella norma storica, hashrate sopra i livelli di un anno fa, dominance al 56 %.
2. **"Ascesa di ETH": segnali reali ma recenti e fragili.** Ratio in recupero (+12 % in 30g), flussi ETF relativi migliori, staking istituzionale. Ma ETH resta −61 % dal massimo e correlato 0,87 con BTC: se BTC crolla, ETH storicamente crolla di più.
3. **La domanda sulla complementarità era quella giusta**: la risposta empirica è che NON sono complementari (correlazione ~0,87), ma la loro *forza relativa* oscilla parecchio — ed è lì che vive l'eventuale trade.

## 7. Riproducibilità

```bash
python3 research/btc_eth/analisi_btc_eth.py
```

Lo script scarica 365 giorni di dati da CoinGecko e ricalcola: correlazioni (365/180/90/30g), performance, ratio ETH/BTC, volatilità, % giorni concordi.

## Fonti

- CoinGecko API (`/simple/price`, `/global`, `/coins/{id}/market_chart`) — prezzi, market cap, dominance, storico
- mempool.space API (`/api/v1/mining/hashrate/1y`) — hashrate e difficulty BTC
- [Yahoo Finance / BeInCrypto — BlackRock sells $230M BTC, buys ETH](https://finance.yahoo.com/markets/crypto/articles/blackrock-sells-230-million-bitcoin-131810369.html)
- [CryptoBriefing — BlackRock BTC→ETH reallocation](https://cryptobriefing.com/blackrock-bitcoin-ethereum-reallocation/)
- [Yellow — Bitcoin miners pivot to AI data centers](https://yellow.com/news/bitcoin-miners-pivot-ai-data-centers-gpu-demand-2026)
- [CoinInsider — $70B AI contracts in mining sector](https://www.coininsider.com/news/bitcoin-miners-are-becoming-ai-infrastructure-companies-heres-whats-driving-it/)
- [CryptoTimes — liquidazioni 14 lug 2026](https://www.cryptotimes.io/2026/07/14/volatility-returns-bitcoin-price-dips-while-liquidations-mount-on-geopolitical-fears/)
- [BitcoinFoundation — $1.8B wipeout 2026](https://bitcoinfoundation.org/news/altcoins/crypto-liquidations-surge-near-1-8b-as-btc-longs-get-crushed/)
- [CryptoBriefing — ETF flows snap 8-week outflow streak](https://cryptobriefing.com/bitcoin-ether-etfs-inflow-ends-outflow-streak/)
- [Phemex — ETH ETF inflows July 2026](https://phemex.com/blogs/ethereum-etf-inflows-break-outflow-streak)
