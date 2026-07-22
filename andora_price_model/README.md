# Stima prezzo appartamento — Andora (SV), litorale / Via Aurelia

Modello in due parti **tenute separate**:

- **Parte 1 — valore oggi** (`parte1_modello.py`): regressione lineare edonica
  (scikit-learn) su poche variabili forti: `mq`, `mq²`, `stato_conservazione`
  (1–4), `distanza_mare_km`, `ascensore`, `garage`. Il numero di locali è
  escluso di proposito (quasi collineare con la metratura).
- **Parte 2 — proiezione a 3 anni** (`parte2_proiezione.py`): **non** è una
  regressione sulle feature. Prende il valore di oggi e applica tre tassi di
  crescita annua composta (pessimista / base / ottimista) ricavati dalla serie
  storica OMI della zona. L'output è una **forbice**, non un numero secco.

## Uso

```bash
pip install pandas numpy scikit-learn
python main.py --mq 75 --stato 3 --distanza-mare 0.2 --ascensore --garage
```

`--stato`: 1=da ristrutturare, 2=abitabile, 3=buono, 4=ristrutturato.

Output: valore di vendita stimato oggi con intervallo (quantili 10–90% dei
residui out-of-fold) + forbice a 3 anni nei tre scenari.

## Dati (cartella `data/`) — cosa è reale e cosa no

| File | Natura | Stato attuale |
|---|---|---|
| `omi_quotazioni_andora.csv` | Quotazioni OMI (€/mq da **compravendite reali**) per zona B3 litorale/Via Aurelia e semicentrale | Valori **approssimativi** trascritti da fonti pubbliche che ripubblicano l'OMI — da sostituire col download ufficiale |
| `omi_storico_andora.csv` | Serie storica €/mq della zona (alimenta gli scenari della Parte 2) | Ricostruzione **approssimativa** del trend — da sostituire con la serie semestrale OMI ufficiale |
| `annunci_andora.csv` | Annunci con **prezzi RICHIESTI** | **Sintetici/illustrativi** (generati da `genera_annunci_esempio.py`, seed fisso) — da sostituire con annunci veri Idealista/Immobiliare.it, stesse colonne |

Per usare dati reali basta sostituire i tre CSV mantenendo le colonne: nessuna
modifica al codice.

## Scelte metodologiche

- **Bias dei prezzi richiesti**: gli annunci sono sistematicamente sopra il
  prezzo di chiusura (tipicamente 10–20%). Vengono scontati del 12%
  (`SCONTO_TRATTATIVA` in `dati.py`) prima del training: il modello stima
  prezzi di **vendita**, non da vetrina.
- **Ancore OMI**: le quotazioni OMI diventano pseudo-osservazioni con peso
  doppio (sono il dato più affidabile perché derivano da atti notarili).
- **Dummy di fonte** (`da_annuncio`): assorbe la differenza di livello residua
  tra annunci scontati e compravendite OMI. Senza, quella differenza si
  scaricherebbe sui coefficienti di ascensore/garage (osservati solo negli
  annunci) distorcendone il segno. In predizione la dummy è 0: la stima è
  ancorata al livello delle compravendite reali. Il suo coefficiente misura il
  bias residuo degli annunci oltre lo sconto del 12%.
- **Validazione**: k-fold (k=5) su dataset piccolo; metriche in euro (MAE,
  MAPE) confrontate con la baseline "€/mq medio OMI della zona × mq". Con i
  dati illustrativi il modello batte la baseline di ~55% di MAE.
- **Scenari Parte 2**: base = CAGR dell'intera serie storica; pessimista /
  ottimista = peggiore / migliore CAGR triennale osservato nella serie. Con la
  serie attuale: ≈ −1,6% / +0,6% / +2,9% annuo.

## Limiti (da leggere)

- Le stime valgono quanto i dati: finché i CSV contengono valori
  approssimativi/illustrativi, l'output è una **demo della metodologia**, non
  una perizia.
- Ascensore e garage sono effetti deboli identificati solo dagli annunci: con
  pochi dati i loro coefficienti restano incerti.
- La proiezione a 3 anni è dichiaratamente uno scenario: eventi non presenti
  nella storia della zona (tassi, normativa, clima, offerta) possono portare
  il prezzo fuori dalla forbice.

## Fonti per i dati reali

- [OMI — Agenzia delle Entrate, quotazioni immobiliari](https://www.agenziaentrate.gov.it/portale/schede/fabbricatiterreni/omi/banche-dati/quotazioni-immobiliari)
  (comune di Andora, zona B3 "Litorale, V. Aurelia, V. Caprera, V. Vignetta")
- [Borsino Immobiliare — Andora](https://borsinoimmobiliare.it/quotazioni-immobiliari/liguria/savona-provincia/andora/)
- [Immobiliare.it — mercato Andora](https://www.immobiliare.it/en/mercato-immobiliare/liguria/andora/)
- [Idealista — report prezzi Andora](https://www.idealista.it/sala-stampa/report-prezzo-immobile/vendita/liguria/savona-provincia/andora/)
- [Mercato-Immobiliare.info — Andora](https://www.mercato-immobiliare.info/liguria/savona/andora/quotazione-appartamento.html)

Riferimenti usati per calibrare i dati illustrativi (luglio 2026): zona OMI B3
abitazioni civili fino a ~5.200 €/mq (massimo, stato ottimo); media annunci
appartamenti Andora ~3.300–3.900 €/mq vicino al mare; trend appartamenti
sostanzialmente piatto (−0,3% su 6 mesi, tra −4% e +0,6% anno su anno a
seconda della fonte).
