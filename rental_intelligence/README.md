# Rental Intelligence Liguria

Sistema multi-agente per l'analisi del mercato degli affitti brevi e delle
opportunità di acquisto a reddito in Liguria.

---

## 1. Si può fare?

Sì, l'architettura funziona e il codice in questa cartella gira end-to-end. Ma
tre punti dell'idea di partenza vanno corretti prima di investirci tempo, e sono
correzioni sostanziali, non dettagli.

### 1.1 Lo scraping di Airbnb e Booking non è un'opzione

I Termini di Servizio di entrambe le piattaforme vietano l'accesso
automatizzato. Non è una zona grigia: è una clausola esplicita, con difese
tecniche attive, e la conseguenza pratica va dal ban dell'infrastruttura alla
diffida legale. In più, raccogliere dati sugli host significa trattare dati
personali di terzi, con gli obblighi GDPR che ne derivano.

Il progetto è comunque fattibile, ma **con altre sorgenti.** In ordine di
rapporto valore/sforzo:

| Sorgente | Cosa dà | Come si ottiene |
|---|---|---|
| **Provider STR in licenza** (AirDNA, Transparent, Key Data, Beyond…) | ADR, occupazione, RevPAR per mercato, già deduplicati | contratto commerciale, a pagamento |
| **Booking.com Demand API** | disponibilità e prezzi Booking | partnership approvata — **avviala per prima, i tempi non dipendono da te** |
| **CIN / registro strutture ricettive** | identificativo unico per unità immobiliare | dato pubblico |
| **OMI — Agenzia delle Entrate** | quotazioni €/mq per zona, semestrali | download gratuito |
| **ISTAT turismo** | arrivi, presenze, capacità ricettiva per comune | download gratuito |
| **Idealista API** | annunci di vendita e affitto | richiesta di accesso, quota gratuita ridotta |
| **I tuoi export** | tutto, sui tuoi immobili | extranet delle piattaforme di cui sei titolare |

Il registro in [`config/sources.yaml`](config/sources.yaml) dichiara lo stato di
conformità di ogni sorgente, e il gate è **nel codice**: un connettore la cui
sorgente è marcata `prohibited` non parte, e non c'è flag per aggirarlo. Le voci
di scraping sono elencate lì con la motivazione del rifiuto, così la scelta è
documentata e non sembra una dimenticanza.

### 1.2 "Il prezzo più conveniente" è la metrica sbagliata

L'idea iniziale prevedeva che il secondo agente selezionasse i prezzi più bassi.
Il problema è che il prezzo da solo non dice nulla:

> Un appartamento a **60 €/notte** riempito per **60 notti** incassa 3.600 €.
> Un appartamento a **95 €/notte** riempito per **140 notti** ne incassa 13.300.

Quello che si ottimizza è il **RevPAR** — ricavo per notte disponibile, cioè
ADR × occupazione — non l'ADR. Un annuncio molto economico spesso lo è perché
non si vende, e ordinarlo in cima a una lista di "affari" è esattamente il modo
di far perdere soldi a chi legge.

### 1.3 L'occupazione non è osservabile

È il vincolo che decide l'affidabilità di tutto il resto. Da fuori si vede solo
se una notte è disponibile o no. Una notte **non disponibile** può essere:

- **venduta** a un ospite → ricavo;
- **bloccata** dal proprietario (uso personale, manutenzione, chiusura
  invernale, un buco di 2 notti reso inprenotabile dal minimo soggiorno) →
  nessun ricavo.

Le due cose sono indistinguibili in una singola rilevazione, e confonderle
**sovrastima** l'occupazione — quindi il ricavo, quindi il rendimento. Sbaglia
cioè proprio nella direzione che ti fa comprare un immobile che non conviene.

L'unico rimedio è **guardare lo stesso calendario più volte nel tempo**: una
notte prima libera e poi chiusa è stata verosimilmente venduta; una notte chiusa
da sempre è bloccata. Da qui discende metà del progetto: [`ri/storage.py`](ri/storage.py)
esiste per conservare le rilevazioni ripetute, e la chiave primaria include
`observed_at` proprio per non sovrascriverle.

Il sistema implementa quattro metodi in ordine di affidabilità decrescente e
**dichiara sempre quale ha usato** (campo `occupancy_method`):

| Metodo | Base | Affidabilità |
|---|---|---|
| `panel` | rilevazioni ripetute nel tempo | alta — l'unico che distingue venduto da bloccato |
| `snapshot` | una rilevazione + assunzione sulle notti bloccate | bassa |
| `reviews` | ritmo delle recensioni | bassa — sottostima gli annunci nuovi |
| `prior` | valori di configurazione | è un'ipotesi, non una misura |

---

## 2. Servono altri agenti? Sì, due

Hai chiesto se il terzo agente basta. La risposta è no: ne servono **cinque più
un supervisore**, e i due che mancavano sono quelli che decidono se il resto ha
senso.

```
START
  │
  ▼
A1 Ingestion ─── nessun dato ─────────────────────────┐
  │                                                    │
  ▼                                                    │
A2 Resolution        ← non era previsto                │
  │                                                    │
  ▼                                                    │
Supervisor           ← non era previsto                │
  │                                                    │
  ├── qualità insufficiente ────────────────┐          │
  ▼                                          ▼          ▼
A3 Market                              A5 Report (modalità bloccata)
  │
  ├── nessun immobile in vendita ─┐
  ▼                               │
A4 Underwriting                   │
  │                               │
  └───────────────┬───────────────┘
                  ▼
              A5 Report
                  │
                 END
```

**A1 — Ingestione.** Interroga le sorgenti abilitate, deposita i payload grezzi.
Non normalizza e non deduce niente: quel lavoro appartiene ad A2 ed è lì che
deve restare per poter essere testato su dati congelati. Una sorgente che
fallisce degrada la copertura, non ferma l'analisi.

**A2 — Risoluzione e deduplica.** *Non era nell'idea di partenza, ed è l'agente
più importante.* Lo stesso appartamento è pubblicato su Airbnb, su Booking e sul
sito dell'agenzia. Se conta come tre immobili, il mercato sembra avere il 30% di
offerta in più di quella reale, e **ogni percentile di prezzo calcolato a valle
è distorto nella stessa direzione.** Non è "un po' impreciso": è
sistematicamente sbagliato, e nessuna raffinatezza dell'analisi lo corregge.

**Supervisore.** *Non era nell'idea di partenza.* Verifica la qualità prima che
gli errori si propaghino. Il rischio specifico: la pipeline produce comunque un
report elegante, con percentili e rendimenti a due decimali, costruito su venti
annunci mal geolocalizzati. Quel report **non sembra sbagliato — sembra
esattamente come uno giusto.** Il gate serve a rendere visibile quel fallimento.

**A3 — Mercato e pricing.** Statistiche per segmento (macro-mercato × tipologia
× fascia di capienza), prezzo consigliato mese per mese, e l'aggancio fra
immobili in vendita e mercato locativo della loro zona. L'unità di analisi è il
segmento, non l'annuncio: un percentile su otto annunci non è un percentile.

**A4 — Valutazione dell'investimento.** Separato da A3 perché *"a che prezzo
affittare"* e *"conviene comprare"* sono due domande diverse, con destinatari
diversi. Un immobile può avere un pricing ottimo e restare un pessimo acquisto.

**A5 — Report.** Narrazione con Claude, oppure template deterministico. Vedi §4.

---

## 3. La deduplica, e perché il CIN cambia tutto

Il matching cross-piattaforma è il problema tecnico più difficile del progetto:

- le coordinate sono **volutamente offuscate** (100–200 m) dalle piattaforme;
- i titoli sono riscritti da zero per ogni canale;
- la capienza dichiarata differisce (divano letto contato o no);
- non esiste una chiave comune… **tranne una**.

Il **CIN** (Codice Identificativo Nazionale) è un identificativo per unità
immobiliare. Dove è esposto, due annunci con lo stesso codice sono lo stesso
immobile *per definizione normativa*: il problema collassa da inferenza
statistica a join esatto. **Alzare la copertura del CIN vale più di qualunque
messa a punto dell'algoritmo di matching**, ed è il motivo per cui il connettore
verso il registro è in cima alla lista delle cose da fare.

Senza CIN, [`ri/analytics/dedup.py`](ri/analytics/dedup.py) usa un punteggio
pesato su segnali indipendenti (geografia con kernel gaussiano tollerante
all'offuscamento, capienza, titolo, servizi, superficie, host) più tre regole
che sono emerse dai test:

1. **Corroborazione minima.** Servono almeno due segnali *forti* e indipendenti.
   Nei centri storici liguri — Vernazza, Portofino — centinaia di annunci stanno
   in poche centinaia di metri con la stessa capienza e gli stessi servizi: un
   punteggio alto costruito su geografia e attributi dice "sono due bilocali in
   centro", non "sono lo stesso bilocale".
2. **Esclusività per sorgente.** Un immobile è pubblicato al massimo una volta
   per piattaforma. Il vincolo chiude la falla della **chiusura transitiva**: se
   A~B e B~C, union-find fonde anche A e C, anche quando sono due annunci della
   stessa piattaforma, cioè proprio la coppia che il confronto diretto si
   rifiuta di valutare. Senza questo vincolo, il test misurava 19 cluster
   corrotti su 420.
3. **Fusione in ordine di punteggio.** Il vincolo rende le fusioni mutuamente
   esclusive, quindi la coppia con l'evidenza più forte deve avere precedenza,
   altrimenti il risultato dipende dall'ordine dell'input.

La regola è **asimmetrica di proposito: preferisce non fondere.** Un duplicato
non riconosciuto gonfia leggermente l'offerta; una fusione sbagliata cancella un
immobile reale e sposta tutti i percentili. Il secondo errore è più grave e
molto più difficile da notare.

Misure sul dataset sintetico, con la verità nota e il CIN rimosso (percorso
puramente probabilistico): **precisione 100%, richiamo 100%** — 519 annunci
ricondotti a 420 immobili. Sui dati veri il richiamo sarà più basso: i duplicati
reali divergono molto più di quelli generati.

---

## 4. Il ruolo dell'LLM (agente 5)

**Claude non calcola niente.** Riceve una scheda-fatti già calcolata da
`analytics/` e la spiega. È una separazione voluta:

- ogni numero è deterministico, testato e rifacibile a mano su un foglio;
- il **verdetto d'investimento è meccanico**, derivato da soglie esplicite in
  `config/fiscale.yaml`. Chi legge deve poter dire *"non sono d'accordo con la
  soglia del 5,5%"* e cambiarla — non *"non sono d'accordo con quello che ha
  pensato il modello"*;
- se l'agente 5 sparisse, il sistema produrrebbe lo stesso identico verdetto.

Il prompt vieta esplicitamente di derivare valori, e lo schema di output non ha
campi in cui il modello potrebbe infilare un numero calcolato. Il payload è
ridotto ai soli segmenti affidabili: contiene i costi, ma soprattutto toglie al
modello il materiale con cui divagare.

Configurazione: `claude-opus-5`, adaptive thinking, output strutturato con
schema JSON, prompt caching sul blocco metodologico, fallback lato server
attivo (`fallbacks="default"`, così un rifiuto dei classificatori viene
rieseguito su un modello di ripiego invece di lasciare un buco). Senza chiave o
con `RI_LLM_ENABLED=false` il report esce da template, con gli stessi numeri.

---

## 5. Come si guadagna

Il sistema non genera ricavi da solo. Abilita tre modelli, in ordine di
difficoltà crescente:

**a) Revenue management sui tuoi immobili.** Il più immediato e l'unico che
funziona con dati che possiedi già. L'agente 3 dice se sei prezzato sotto il
posizionamento del tuo segmento e di quanto, mese per mese. Su un immobile che
fa 20.000 € l'anno, 8 punti di prezzo recuperati sono 1.600 €. Costo dei dati:
zero, sono i tuoi export.

**b) Report di mercato venduti a proprietari e agenzie.** Il prodotto è
l'analisi, non il dato: puoi venderla anche partendo da dati acquistati in
licenza (quasi tutti i contratti vietano la ridistribuzione del dato granulare,
non delle analisi che ne derivi — **verifica il tuo contratto**). Richiede
copertura credibile di almeno un macro-mercato.

**c) Scouting per investitori.** L'agente 4 filtra gli annunci di vendita per
rendimento netto atteso. È il più difficile perché richiede *entrambi* i lati —
mercato locativo e mercato della compravendita — e la qualità della stima di
occupazione diventa critica: un errore del 10% sull'occupazione si trasmette
tutto sul rendimento.

Ordine consigliato: **(a) → (b) → (c)**. (a) valida il modello su dati che
controlli, prima di venderlo o di metterci soldi tuoi.

---

## 6. Uso

```bash
pip install -r rental_intelligence/requirements.txt
cp rental_intelligence/.env.example rental_intelligence/.env   # opzionale

# elenco delle sorgenti e loro stato di conformità
python -m rental_intelligence.ri.cli sources

# i 12 macro-mercati configurati
python -m rental_intelligence.ri.cli markets

# pipeline completa (sorgente `demo` = dati sintetici)
python -m rental_intelligence.ri.cli run --mercati cinque_terre,tigullio

# valutazione singola di un acquisto, senza pipeline
python -m rental_intelligence.ri.cli underwrite \
    --prezzo 240000 --adr 155 --occ 0.52 --mq 60 --rendita 700 \
    --mercato cinque_terre

python -m pytest rental_intelligence/tests -q
```

La sorgente `demo` genera un dataset sintetico calibrato sui prior liguri. Serve
a far girare tutto senza dipendere da fonti esterne e a dare ai test una verità
nota. **Non contiene dati reali**, e il report lo dichiara in testa.

### Struttura

```
config/          liguria.yaml (geografia, stagionalità), fiscale.yaml (costi e
                 imposte), sources.yaml (registro sorgenti + conformità)
ri/models.py     contratto dati fra gli agenti
ri/geo.py        distanze, comune → macro-mercato, alias delle frazioni
ri/storage.py    SQLite; conserva le rilevazioni ripetute (→ occupazione panel)
ri/connectors/   base (gate di conformità), demo, csv_import, API ufficiali
ri/analytics/    dedup, revenue, pricing, finance — deterministici, nessun LLM
ri/agents/       i 5 agenti + supervisore
ri/llm/          client Claude e prompt dell'agente 5
ri/orchestrator.py
tests/           51 test
```

---

## 7. Il modello finanziario

Un punto che quasi tutti i calcolatori online sbagliano: **sotto cedolare secca
la base imponibile è il corrispettivo lordo**, comprese le somme addebitate
all'ospite per le pulizie, e **le commissioni delle piattaforme non sono
deducibili**. Con commissioni OTA al 16% e property management al 20%, la
cedolare al 21% su 20.000 € di lordo costa 4.200 € pur essendo il margine reale
molto più basso. È il caso in cui il regime ordinario, che tassa il netto, può
convenire: il modello calcola entrambi, usa il migliore e riporta quanto costa
l'alternativa.

Il resto: costi di acquisizione completi (il denominatore del rendimento è il
costo totale, non il prezzo — sul solo prezzo il rendimento si gonfia del
10-20%), conto economico annuo, IMU, mutuo con ammortamento francese, VAN, TIR,
payback, **break-even occupancy** e griglia di sensibilità.

Il break-even è la metrica singola più leggibile: dice quante notti servono per
non perdere soldi, ed è confrontabile con l'occupazione media del segmento. Ma
è il pareggio *di cassa*, non il rendimento sul capitale — un immobile può avere
break-even al 25% e rendere lo 0,8%, perché copre le spese correnti senza
remunerare i 330.000 € investiti. Le due metriche vanno lette insieme.

> ⚠️ **Le aliquote in `config/fiscale.yaml` non sono verificate contro la
> normativa vigente e non sono consulenza fiscale.** La fiscalità delle
> locazioni brevi in Italia è cambiata più volte negli ultimi anni. Fai validare
> le voci marcate `verify: true` da un commercialista e le imposte d'atto da un
> notaio. Il codice non hardcoda nessun numero: legge solo da quel file.

---

## 8. Cosa manca

In ordine di priorità:

1. **Accesso a una sorgente reale.** Tutto il resto è pronto e aspetta questo.
   Le API ufficiali in [`ri/connectors/official_apis.py`](ri/connectors/official_apis.py)
   hanno firma, gate e mapping; manca la chiamata HTTP, deliberatamente: senza
   aver letto la documentazione contrattuale, scriverla significherebbe
   consegnare codice che sembra funzionante e non lo è. Il punto di rottura è
   segnato con `NotImplementedError` e un messaggio che dice cosa serve.
2. **Raccolta ripetuta nel tempo.** Un job programmato che accumula rilevazioni
   in SQLite. Finché `panel_depth()` riporta profondità media 1, l'occupazione è
   assunta e non misurata, e ogni rendimento è uno scenario.
3. **Codici ISTAT.** Da caricare dal file ufficiale con
   `geo.load_istat_codes()`. Non sono hardcoded di proposito: un codice ISTAT
   inventato corrompe silenziosamente ogni join con le statistiche ufficiali.
4. **Parser OMI**, per validare i prezzi di vendita contro i valori di zona.
5. **Calibrazione dei prior stagionali** sui dati osservati
   (`pricing.calibrate_seasonality`, che si rifiuta di girare con meno di 12
   mesi di dati).
6. **UI Streamlit**, riusando l'impostazione di `streamlit_app/` già nel repo.

---

## 9. Limiti dichiarati

- I dati `demo` sono sintetici. Nessuna conclusione di mercato che ne deriva è
  valida.
- Con `occupancy_method` diverso da `panel`, i rendimenti sono **scenari**.
- I prior stagionali in `liguria.yaml` sono ipotesi di partenza, non misure.
- La deduplica misurata al 100% sul sintetico avrà richiamo più basso sul reale.
- I parametri fiscali non sono verificati (§7).
- Il sistema non considera vincoli paesaggistici, regolamenti condominiali sulle
  locazioni turistiche, limiti comunali agli affitti brevi né spese
  straordinarie deliberate. Sono tutti fattori che possono annullare un
  investimento apparentemente buono, e vanno verificati a mano.

L'orchestratore è Python semplice, senza LangGraph, a differenza di
`multiagent_pipeline/main.py`. La topologia è la stessa e la traduzione è
meccanica (ogni `run` → nodo, ogni `after_*` → `add_conditional_edges`); la
scelta è per far girare il modulo senza dipendenze aggiuntive.
