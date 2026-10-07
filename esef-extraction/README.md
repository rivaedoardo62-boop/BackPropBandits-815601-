# esef-extraction

Prototipo per estrarre indicatori finanziari dalle relazioni degli emittenti quotati italiani e
produrre dati strutturati, tracciabili e validati per alimentare un sistema di risk scoring.
Il calcolo del risk score è fuori perimetro.

**Fase 1**: setup, campione di test, estrattore ESEF deterministico. Niente LLM.

## Stato

| Passo | Contenuto | Stato |
|-------|-----------|-------|
| 1 | Struttura del progetto, Dockerfile, dipendenze fissate | fatto |
| 2 | Verifica dell'API ed elenco relazioni IT | fatto, vedi [`docs/api_notes.md`](docs/api_notes.md) |
| 3 | Proposta di campione | **in attesa di approvazione** |
| 4 | Download xBRL-JSON e pacchetti, manifest con SHA-256 | da fare dopo l'approvazione |
| 5 | `config/indicators.yaml` | da fare |
| 6 | Estrattore ESEF | da fare |
| 7 | Validazione | da fare |
| 8 | Report di copertura | da fare |
| 9 | Modelli vuoti per l'annotazione manuale | da fare |

## Vincoli di progetto applicati nel codice

- Unica fonte di download: `filings.xbrl.org`. `PoliteSession` rifiuta qualsiasi altro host.
- Almeno 1 secondo tra due richieste (default 1,5 s; valori < 1 sono rifiutati) e User-Agent descrittivo.
- Nessuna credenziale: l'API è pubblica. `.env` è escluso da git e dall'immagine Docker.
- Dipendenze con versioni fissate in `pyproject.toml`; albero completo con hash in `requirements.lock`.
- Nessun valore viene stimato o corretto: le anomalie vengono segnalate in colonne dedicate.

## Struttura

```
esef-extraction/
  src/extraction/
    sources/      client API (http.py, filings_api.py)
    esef/         estrattore (Passo 6)
    schema/       schema degli indicatori (Passo 5)
    validation/   controlli (Passo 7)
    report/       report di copertura (Passo 8)
    sample.py     candidati e proposta di campione (Passo 3)
    cli.py        riga di comando
  config/
    sample_proposal.yaml   proposta di campione (settore e segmento DA VERIFICARE)
    indicators.yaml        segnaposto per il Passo 5
  data/{raw,interim,output}/   esclusi da git e dall'immagine Docker
  annotations/                 annotazioni manuali (esclusi dall'immagine Docker)
  docs/api_notes.md            verifica dell'API
  tests/
```

## Esecuzione locale

Richiede Python 3.11.

```bash
cd esef-extraction
python3.11 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/pip install --no-deps -e .

cp .env.example .env        # compilare il contatto nel User-Agent
set -a; . ./.env; set +a

# Passo 2: elenco relazioni IT (5 richieste all'API)
.venv/bin/python -m extraction.cli fetch-filings --country IT
# Passo 3: candidati (FY2024 e FY2025 con xBRL-JSON) e proposta
.venv/bin/python -m extraction.cli sample-candidates
.venv/bin/python -m extraction.cli propose-sample

# Test
.venv/bin/python -m pytest
```

`pipeline` esegue offline tutti i passi disponibili sulle risposte API già salvate in
`data/raw/api/` (nessuna richiesta di rete):

```bash
.venv/bin/python -m extraction.cli pipeline
```

Per rigenerare `requirements.lock` dopo aver cambiato una versione:

```bash
uv pip compile --python-version 3.11 --python-platform x86_64-manylinux_2_28 \
  --generate-hashes requirements.in -o requirements.lock
```

(`requirements.in` contiene le cinque dipendenze dirette di `pyproject.toml` più `pytest`, con le stesse versioni.)

## Esecuzione con Docker

L'immagine contiene solo codice, configurazione e test; i dati si montano a runtime.
L'utente nel container è non-root (uid 10001). Per scrivere nella cartella `data/` montata con i
permessi dell'utente host si usa `--user "$(id -u):$(id -g)"`.

```bash
docker build -t esef-extraction .
# dietro un proxy con ispezione TLS: CA passata come secret, non resta nell'immagine
docker build --secret id=ca_bundle,src=/percorso/ca.pem -t esef-extraction .
# pipeline offline sui file già scaricati
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/app/data" esef-extraction
# test
docker run --rm esef-extraction python -m pytest
# aggiornamento dell'elenco relazioni (unico comando che usa la rete)
docker run --rm --user "$(id -u):$(id -g)" --env-file .env -v "$PWD/data:/app/data" \
  esef-extraction python -m extraction.cli fetch-filings --country IT
```

## Output del Passo 2 e 3

| File | Contenuto |
|------|-----------|
| `data/raw/api/filings_it_<timestamp>/` | risposte grezze dell'API e `_meta.json` (data e URL della richiesta) |
| `data/interim/filings_it.csv` | una riga per relazione: entità, LEI, fine periodo, indizio di lingua, data di aggiunta, hash API, link xBRL-JSON e pacchetto, errori/avvisi di validazione |
| `data/interim/sample_candidates.csv` | relazioni FY2024 e FY2025 degli emittenti con xBRL-JSON per entrambi gli esercizi; tipo di versione e versione proposta |
| `data/interim/sample_proposal.csv` | i 20 emittenti proposti, con tutte le versioni e `proposed_version` |

## Decisioni aperte

1. **Approvazione del campione** (`config/sample_proposal.yaml`): settore e segmento di mercato sono
   indicati a mano e vanno verificati su fonti ufficiali.
2. **Versioni multiple dello stesso esercizio.** Regola proposta: xBRL-JSON presente → lingua
   italiana se esistono più lingue → versione aggiunta per ultima. Alternativa più prudente:
   scaricare tutte le versioni degli emittenti approvati ed estrarre i fact da ciascuna; se i valori
   coincidono la scelta è irrilevante, se differiscono si segnala.
3. **Lingua**: l'API non la espone; l'indizio dal nome file non è un dato. Va deciso se serve.
4. **Esercizio**: anno di `period_end`. Gli esercizi non solari sono esclusi dalla proposta; serve
   una convenzione se verranno inclusi. `period_end` dell'API è errato in alcuni casi: il periodo
   andrà confermato dai fact.
5. **Copertura**: filings.xbrl.org non copre tutti gli emittenti italiani (mancano, ad esempio,
   i 2025 di Enel, UniCredit, Poste). Per un uso oltre il prototipo serve la fonte ufficiale.
6. **User-Agent**: quale contatto indicare (personale o istituzionale) è una scelta da concordare.
7. **Banche e assicurazioni**: gli indicatori richiesti sono pensati per imprese industriali;
   per i 3 emittenti finanziari molti risulteranno non applicabili. Va deciso se trattarli come
   "mancante" o "non applicabile".
