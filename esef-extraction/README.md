# esef-extraction - Fase 1

Prototipo per estrarre indicatori finanziari dalle relazioni degli emittenti
quotati italiani e produrre dati strutturati, tracciabili e validati per il
sistema di risk scoring (P122, Wave 2 del sistema 89-quater). Il calcolo del
risk score e' fuori perimetro. In questa fase: niente LLM, niente agenti.

## Stato

| Passo | Contenuto | Stato |
|---|---|---|
| 1 | Struttura del progetto, Docker, dipendenze fissate | fatto |
| 2 | Verifica dell'API ed elenco delle relazioni IT | fatto ([docs/api_notes.md](docs/api_notes.md)) |
| 3 | Proposta di campione (20 emittenti + 7 riserve) | fatto, **in attesa di approvazione** |
| 4-9 | Download, schema indicatori, estrattore, validazione, report, modelli di annotazione | non iniziati: partono solo dopo l'approvazione |

`config/indicators.yaml` e i pacchetti `esef`, `validation`, `report` sono
segnaposto per i Passi 5-8.

## Regole che il codice rispetta

1. Nessun valore finanziario inventato o stimato: un dato assente resta mancante.
2. Provenienza di ogni dato: pagine originali dell'API conservate con SHA-256,
   ora dello snapshot su ogni riga, hash dei pacchetti.
3. Il riferimento manuale (giudizio del revisore, ricavi per area, semestrali)
   lo compila solo l'annotatore: il codice prepara al massimo modelli vuoti.
4. Unica fonte contattata: l'API di filings.xbrl.org (e i link che restituisce,
   solo sullo stesso host). Nessuno scraping di 1Info, eMarket Storage o siti
   degli emittenti: i PDF si scaricano a mano. Almeno 1 s tra due richieste
   (anche nei retry) e User-Agent descrittivo; valori di ritardo < 1 s sono
   rifiutati.
5. Nessuna credenziale nel codice; dipendenze con versione fissata e hash.

## Struttura

```
esef-extraction/
  src/extraction/
    sources/      client HTTP (ritardo, User-Agent, retry), API, indice, prove API
    schema/       contratti dei dati (pydantic)
    esef/         estrattore xBRL-JSON (Passo 6)
    validation/   controlli (Passo 7)
    report/       report di copertura (Passo 8)
    sample.py     proposta del campione (Passo 3)
    cli.py        comandi: python -m extraction <comando>
  config/
    sample.yaml       campione proposto: emittenti, settore/segmento proposti, stato
    indicators.yaml   schema degli indicatori (Passo 5)
  data/{raw,interim,output}/   dati scaricati e generati (non versionati)
  annotations/      modelli per l'annotazione manuale (Passo 9)
  docs/api_notes.md verifiche sull'API e problemi trovati nei metadati
  tests/            test offline (nessuna chiamata di rete)
```

## Installazione locale (Python 3.11)

```bash
cd esef-extraction
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --require-hashes -r requirements.lock
pip install --no-deps -e .
cp .env.example .env                 # facoltativo: User-Agent, ritardo, cartelle
pytest
```

## Esecuzione

```bash
# Passo 2 - elenco completo delle relazioni italiane (online, ~5 richieste)
python -m extraction filings-index --country IT
#   -> data/interim/filings_it.csv, data/interim/filings_it.meta.json,
#      data/raw/api/filings_it_<timestamp>/page_*.json

# Passo 2 - ripete le richieste di prova documentate in docs/api_notes.md
python -m extraction verify-api --lei 815600115DA6E507AE33 --period-end 2025-12-31
#   -> data/interim/api_probe.json (codice di uscita 1 se l'API e' cambiata)

# Passo 3 - proposta di campione (offline)
python -m extraction sample-proposal
#   -> data/interim/sample_proposal.csv

# Tutti gli stadi offline sui dati gia' scaricati (per ora: la proposta)
python -m extraction pipeline
```

## Docker

L'immagine (base `python:3.11-slim`, utente non root, nessun dato copiato)
esegue gli stadi offline; i dati si montano come volume.

```bash
docker build -t esef-extraction .

# stadi offline sui file gia' presenti in ./data
docker run --rm -v "$PWD/data:/app/data" --user "$(id -u):$(id -g)" esef-extraction

# comandi online (scaricano dall'API)
docker run --rm -v "$PWD/data:/app/data" --user "$(id -u):$(id -g)" \
  --env-file .env esef-extraction filings-index --country IT

# test nel container
docker run --rm --entrypoint pytest esef-extraction -q
```

Su Windows (PowerShell) usare `${PWD}` e omettere `--user`.

## Come leggere e approvare la proposta di campione

`data/interim/sample_proposal.csv` ha una riga per emittente x esercizio x
versione della relazione:

- `status`: `proposed` (nel campione) o `reserve` (riserva);
- `sector_group`, `sector_to_verify`, `segment_to_verify`: **proposte**
  dell'assistente, da verificare (l'API non riporta settore ne' indice);
- `n_versions`, `version_flag`, `lang_hint_filename`, `proposed_version`,
  `choice_reason`: versioni multiple dello stesso esercizio e quale si propone
  di usare (regole in `src/extraction/sample.py`);
- `sha256`, `json_url`, `package_url`, `error_count`: dati dell'API.

Per approvare: cambiare `status` in `config/sample.yaml` (`proposed` ->
`approved` o `rejected`; una riserva sostituisce uno scartato con
`approved`), oppure indicare le modifiche in chat. Il Passo 4 scarichera'
solo gli emittenti `approved`.

## Decisioni aperte

1. **Settore e segmento** degli emittenti del campione: proposte da verificare
   (composizione FTSE Italia aggiornata trimestralmente).
2. **Lingua**: l'API non la espone. Il suffisso `-it`/`-en` dei nomi file e'
   usato solo come indizio. Proposta: determinarla dal contenuto dopo il
   download (dimensione `language` dei fact testuali).
3. **Versioni multiple** dello stesso esercizio (140 casi nell'elenco IT):
   regole proposte in `sample.py`; per i casi non distinguibili dai metadati
   (es. UniCredit 2024, quattro versioni) proposta di scaricare tutte le
   versioni e confrontarle. Nel campione l'unico caso e' Italgas (italiano/
   inglese).
4. **Esercizio** = anno della data di fine periodo, solo chiusure al 31/12:
   esclusi gli esercizi non solari (es. OVS, Juventus). Da confermare.
5. **Perimetro**: esclusi gli emittenti non di diritto italiano presenti
   nell'elenco IT (Brembo N.V., Ariston Holding N.V., Tenaris S.A., ...).
   Da confermare.
6. **Banche e assicurazioni**: molti indicatori (ricavi, risultato operativo,
   rimanenze, crediti commerciali) non si applicano agli schemi bancari e
   assicurativi; serve decidere se definire indicatori specifici.
7. **Metadati inaffidabili**: in 7 relazioni `period_end` non coincide con la
   data nel nome del file (es. Recordati "2032-12-31"): il periodo andra'
   ricontrollato sui contesti dei fact al Passo 6.
8. **User-Agent**: oggi non contiene un contatto. Decidere se indicare un
   recapito istituzionale (nessun dato personale e' stato inserito nel codice).
9. **Snapshot non versionati**: `data/` e' escluso da git come richiesto, quindi
   l'elenco e la proposta non sono nel repository; si rigenerano con i comandi,
   ma filings.xbrl.org aggiunge relazioni nel tempo. Per l'audit conviene
   archiviare lo snapshot usato (CSV + `.meta.json`) in un luogo controllato.
10. **Repository**: il prototipo e' in una sottocartella di un repository
    universitario non correlato. Prima di condividerlo in CONSOB conviene
    spostarlo in un repository dedicato.

## Aggiornare dipendenze e immagine

```bash
# dopo aver cambiato una versione in pyproject.toml
uv pip compile pyproject.toml --extra dev --universal --python-version 3.11 \
  --generate-hashes -o requirements.lock
```

Il lock contiene tutte le dipendenze transitive con hash; Docker installa con
`--require-hashes`. L'immagine di base `python:3.11-slim` e' fissata per
digest nel `Dockerfile`; per aggiornarla (es. patch di sicurezza):

```bash
docker buildx imagetools inspect python:3.11-slim   # copiare il "Digest" nel FROM
```
