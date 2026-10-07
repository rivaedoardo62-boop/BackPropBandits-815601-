# esef-extraction

Prototipo per estrarre indicatori finanziari dalle relazioni degli emittenti quotati italiani
e produrre dati strutturati, tracciabili e validati, destinati ad alimentare un sistema di
risk scoring. **Il calcolo del risk score è fuori perimetro.**

Questa è la **Fase 1**: setup, campione di test ed estrattore ESEF deterministico.
Niente LLM, niente agenti.

## Stato dei lavori

| Passo | Contenuto | Stato |
|---|---|---|
| 1 | Struttura del progetto, Docker, dipendenze fissate | fatto |
| 2 | Verifica dell'API ([docs/api_notes.md](docs/api_notes.md)) ed elenco delle relazioni IT | fatto |
| 3 | Proposta di campione (20 emittenti, esercizi 2024 e 2025) | **fatto, in attesa di approvazione** |
| 4 | Download di xBRL-JSON e report package + `manifest.csv` | da fare dopo l'approvazione |
| 5 | `config/indicators.yaml` | da fare dopo l'approvazione |
| 6 | Estrattore deterministico → `facts_esef.parquet/.csv` | da fare dopo l'approvazione |
| 7 | Validazione → `validation_report.csv` | da fare dopo l'approvazione |
| 8 | Report di copertura → `coverage_report.md` | da fare dopo l'approvazione |
| 9 | Modelli vuoti per l'annotazione manuale dei PDF | da fare dopo l'approvazione |

## Regole del progetto e come il codice le applica

| Regola | Dove |
|---|---|
| Mai inventare o stimare valori: un dato assente è mancante | estrattore (Passo 6) |
| Provenienza completa di ogni valore (documento, SHA-256, concetto, periodo, unità, decimali, id del fact) | manifest (Passo 4) ed estrattore (Passo 6) |
| Il riferimento manuale lo compila solo l'utente | Passo 9: solo modelli vuoti |
| Dati scaricati **solo** da filings.xbrl.org tramite la sua API | `PoliteSession` rifiuta qualunque URL fuori da `https://filings.xbrl.org`, anche dopo un redirect |
| Almeno 1 s tra le richieste, User-Agent descrittivo | `PoliteSession`: intervallo minimo 1 s imposto dal codice (default 1,5 s) |
| Nessuna credenziale nel codice; dipendenze fissate | nessuna credenziale necessaria; `pyproject.toml` + `requirements.lock` con hash; immagine base fissata per digest |
| Informazioni non verificabili: chiedere invece di assumere | [docs/api_notes.md](docs/api_notes.md) §7 e "Decisioni aperte" sotto |
| Download solo dopo l'approvazione del campione | `config/sample_candidates.yaml` ha `status: proposta`; il download (Passo 4) partirà solo con `status: approvata` |

## Struttura

```
esef-extraction/
  src/extraction/
    cli.py                 comandi `esef ...`
    settings.py            configurazione da variabili d'ambiente
    sources/               http.py (accesso "educato" all'API), filings_api.py, listing.py (Passo 2), sample.py (Passo 3)
    schema/                contratti dei dati (sample.py; indicatori al Passo 5)
    esef/ validation/ report/   Passi 6, 7, 8
  config/
    sample_candidates.yaml proposta di campione (da approvare)
    indicators.yaml        Passo 5 (ancora vuoto)
  data/{raw,interim,output}/   esclusi da git e dall'immagine Docker
  annotations/             Passo 9
  docs/api_notes.md        verifiche sull'API e sul formato
  tests/                   pytest, nessun accesso alla rete
```

## Installazione

Locale (Python 3.11):

```bash
cd esef-extraction
python3.11 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements.lock
pip install --no-deps -e .          # comando `esef`; in alternativa: PYTHONPATH=src python -m extraction
cp .env.example .env                # facoltativo: contatto nello User-Agent, proxy aziendale
set -a; . ./.env; set +a
```

Docker:

```bash
docker build -t esef-extraction .
# dietro un proxy con ispezione TLS (la CA non resta nell'immagine):
docker build --secret id=ca_bundle,src=/percorso/ca-aziendale.pem -t esef-extraction .
```

## Esecuzione

### Passo 2 – elenco delle relazioni italiane (richiede rete)

```bash
esef list-filings --country IT
```

Produce:
- `data/interim/filings_it.csv`: una riga per relazione (entità, LEI, fine periodo, `language_hint`,
  data di aggiunta, SHA-256 del pacchetto, link xBRL-JSON, link pacchetto, errori/warning di validazione,
  più colonne di controllo come `period_end_matches_filename` e `n_filings_same_lei_period`);
- `data/interim/filings_it.meta.json`: query, data/ora, User-Agent, numero di pagine;
- `data/raw/api/filings_it/<timestamp>/page-*.json`: risposte grezze dell'API.

### Passo 3 – proposta di campione (offline)

```bash
esef propose-sample
```

Legge `filings_it.csv` e `config/sample_candidates.yaml` e produce:
- `data/interim/sample_proposal.csv`: una riga per **versione** di relazione dei 20 emittenti proposti,
  con `proposed_use` (Y/N), regola applicata (`version_rule`), nota e `needs_review`;
- `data/interim/eligible_issuers.csv`: tutti gli emittenti eleggibili, per sostituire un candidato;
- `data/interim/sample_proposal.summary.json`: composizione per gruppo, indice e STAR.

**Settore, indice e STAR sono proposte non verificate** (filings.xbrl.org non li fornisce).

Regole di scelta della versione (dettagli in `src/extraction/sources/sample.py`):
escluse le versioni senza xBRL-JSON (R1) o con periodo incoerente (R2); preferita la versione con
suffisso `it` (R3); pacchetti identici contati una volta (R4); tra le rimanenti la più recente (R5).
Le scelte basate su R3/R5 hanno `needs_review=Y`: si basano su metadati non verificati e verranno
confermate dopo il download confrontando i valori numerici delle versioni.

### Approvare il campione

1. Verificare settore, indice e STAR su fonti ufficiali e correggere `config/sample_candidates.yaml`
   (per sostituire un emittente: `data/interim/eligible_issuers.csv`).
2. Impostare `status: approvata`, `approved_by`, `approved_on` (il codice rifiuta un'approvazione senza firma).
3. Rieseguire `esef propose-sample` e versionare la configurazione: il commit è la traccia dell'approvazione.

### Pipeline offline

```bash
esef run       # oggi: Passo 3 sui file già presenti; i Passi 4-9 si aggiungeranno qui
```

Con Docker (i dati restano sull'host; `--user` evita problemi di permessi sulla cartella montata):

```bash
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/app/data" esef-extraction            # esef run
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/app/data" esef-extraction list-filings --country IT
docker run --rm --entrypoint python esef-extraction -m pytest                                    # test
```

Dietro un proxy aziendale aggiungere `-e HTTPS_PROXY=...` e, se serve un certificato,
`-v /percorso/ca.pem:/certs/ca.pem:ro -e REQUESTS_CA_BUNDLE=/certs/ca.pem`.

### Test

```bash
pytest
```

I test usano risposte HTTP simulate e non accedono alla rete.

## Decisioni aperte

Per l'utente o il tutor:

1. **Approvazione del campione** e verifica di settore, indice e STAR (Passo 3).
2. **Esercizio fiscale**: oggi `fiscal_year` = anno della data di chiusura e solo esercizi chiusi al 31/12.
   Esclusi quindi, ad esempio, OVS (31/01), Digital Bros e S.S. Lazio (30/06), Abitare In (30/09).
   Includerli richiede una convenzione esplicita.
3. **Versione da usare** quando ci sono più versioni dello stesso esercizio: proposta la versione italiana
   come primaria e la più recente a parità di lingua. Va confermato che la versione italiana sia quella di riferimento.
4. **Lingua**: l'API non la espone; il suffisso del nome file non è affidabile (caso De' Longhi FY2025,
   vedi api_notes §6.3). Proposta: determinarla dopo il download dal contenuto dei fact testuali.
5. **Banche e assicurazioni**: molti indicatori (ricavi, rimanenze, crediti commerciali, EBITDA) non sono
   applicabili. Proposta per il Passo 5: distinguere nel report "non applicabile" da "mancante",
   altrimenti la copertura risulta artificialmente bassa.
6. **REVENUE**: alcuni emittenti non usano `ifrs-full:Revenue` (es. `RevenueFromContractsWithCustomers`).
   Aggiungere concetti candidati cambia la definizione dell'indicatore: va deciso esplicitamente.
7. **BORROWINGS** (definizione della leva) ed **EBITDA** (solo estensioni con etichetta "EBITDA"): Passo 5.
8. **Collocazione del codice**: questa cartella vive dentro un repository di un altro progetto. È consigliabile
   spostarla in un repository dedicato e verificare la visibilità del repository prima di aggiungervi
   informazioni interne.

## Problemi trovati nei dati ESEF

Sintesi (dettagli e richieste di prova in [docs/api_notes.md](docs/api_notes.md)):
- `period_end` dell'API incoerente con il nome del file in 8 relazioni IT (es. Recordati 2032-12-31 per l'esercizio 2022);
- 45 coppie emittente/periodo con più relazioni negli esercizi 2024-2025 (versioni IT/EN, ri-depositi, duplicati identici);
- copertura del 2025 ancora parziale: 110 emittenti contro 165 del 2024 (indice in aggiornamento);
- le etichette dei concetti di estensione (necessarie per EBITDA) non sono nello xBRL-JSON ma nel report package.
