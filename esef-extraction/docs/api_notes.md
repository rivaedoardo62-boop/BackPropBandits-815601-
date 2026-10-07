# Note sull'API di filings.xbrl.org (Passo 2)

Verifica eseguita il **2026-10-07**. Le richieste sono state fatte con User-Agent descrittivo e
almeno 1 secondo tra una richiesta e l'altra.

## 1. Cosa dice la documentazione ufficiale

Fonte: <https://filings.xbrl.org/docs/api>

- URL base: `https://filings.xbrl.org/api`
- Risorse: `filings`, `entities`, `validation_messages`
- Standard: JSON:API 1.0
- Paginazione: `page[size]`, `page[number]`; i link alle altre pagine sono in `links`
- Filtri: `filter[<attributo>]=<valore>` (es. `filter[country]=GB`) e filtri complessi con la
  sintassi della libreria sottostante
- Ordinamento: `sort` (es. `sort=-processed`); inclusione di risorse collegate: `include=entity`
- Condizioni d'uso: gratuito, ma "we reserve the right to alter the API at any time, including
  applying rate limits or withdrawing it completely"; per uso regolare è consigliata l'iscrizione
  alla mailing list.

**La documentazione non elenca gli attributi delle risorse.** Nomi e significati che seguono
sono stati verificati con le richieste di prova del §2, non presi dalla documentazione.

## 2. Richieste di prova

| # | Richiesta | Esito | Cosa verifica |
|---|-----------|-------|---------------|
| 1 | `GET /api/filings?filter[country]=IT&page[size]=2&include=entity` | 200, `meta.count` = 873 | filtro Paese; attributi di `filing` ed `entity` |
| 2 | `GET /api/filings?filter=[{"name":"country","op":"eq","val":"IT"},{"name":"period_end","op":"eq","val":"2025-12-31"}]&page[size]=1` | 200, `meta.count` = 118 | filtro complesso su `period_end` (sintassi `name`/`op`/`val`) |
| 3 | `GET /api/entities/8156001A772766DCAA71/filings` | 200, 5 relazioni | ricerca per LEI tramite la risorsa `entity` |
| 4 | `GET /api/filings?filter=[{"name":"entity","op":"has","val":{"name":"identifier","op":"eq","val":"8156001A772766DCAA71"}}]` | 200, stesse 5 relazioni | filtro per LEI sulla risorsa `filings` |
| 5 | `GET /api/filings?filter[country]=IT&page[size]=500` | 200, 500 righe | nessun limite evidente a 500 righe; si usa comunque 200 (valore dell'esempio ufficiale) |
| 6 | `GET /api/filings?filter[country]=IT&page[size]=3&sort=id` | 200, id crescenti | ordinamento per `id` (usato per una paginazione stabile) |
| 7 | `HEAD` su un `json_url` e un `package_url` | 200, `application/json` e `application/zip` (20,8 MB) | i link sono relativi al dominio e scaricabili |
| 8 | `GET /api/validation_messages?page[size]=1` | 200, attributi `severity`, `message`, `code` | dettaglio dei messaggi di validazione |

Per ogni relazione il dettaglio dei messaggi è in `relationships.validation_messages.links.related`
(`/api/filings/<id>/validation_messages`). Non è stato ancora usato.

## 3. Corrispondenza campi richiesti → attributi reali

| Campo richiesto | Attributo API | Note |
|-----------------|---------------|------|
| Paese | `filing.country` (filtro `filter[country]=IT`) | È il Paese del sistema di deposito, non la sede dell'emittente: compaiono ad es. *BB Biotech AG* e *Prysmian Group North Europe AB*. |
| LEI | `entity.identifier` (con `include=entity`) | Non è un attributo di `filing`. Coincide con i primi 20 caratteri di `fxo_id`. Cifre di controllo ISO 17442 corrette per tutti i 225 LEI. |
| Entità | `entity.name` | Il nome può non corrispondere all'emittente quotato atteso (es. il LEI `815600B7FD80E48C1896` è denominato "A2A ENERGIA S.P.A."): va verificato su GLEIF. |
| Fine periodo | `filing.period_end` | **Non sempre affidabile**, vedi §5. |
| Lingua | **non disponibile** | Nessun attributo. Si ricava solo un *indizio* dal suffisso del nome file (`-it`, `-en`), colonna `lang_hint_from_filename`. |
| Data di aggiunta | `filing.date_added` | Esiste anche `filing.processed` (data di elaborazione). |
| Hash | `filing.sha256` | **Semantica non documentata.** Si presume sia l'hash del report package: da verificare al Passo 4 confrontandolo con lo SHA-256 del file scaricato. Nel CSV è `api_sha256`. |
| Link xBRL-JSON | `filing.json_url` | Percorso relativo a `https://filings.xbrl.org`. Nullo per 9 relazioni IT. |
| Link pacchetto | `filing.package_url` | Percorso relativo. |
| Errori di validazione | `filing.error_count` | Disponibili anche `warning_count` e `inconsistency_count`. |
| (extra) Identificativo | `filing.fxo_id` | Forma osservata: `<LEI>-<period_end>-ESEF-<Paese>-<n>`; `<n>` distingue più relazioni per lo stesso periodo. |
| (extra) Visualizzatore, report | `filing.viewer_url`, `filing.report_url` | Percorsi relativi. |

## 4. Elenco scaricato: `data/interim/filings_it.csv`

- Comando: `python -m extraction.cli fetch-filings --country IT`
- Richiesta: `GET /api/filings?filter[country]=IT&include=entity&sort=id&page[size]=200`, 5 pagine
- Risposte grezze conservate in `data/raw/api/filings_it_<timestamp>/` (con `_meta.json`);
  il CSV si può rigenerare offline con `--from-raw`
- Controllo: righe distinte = `meta.count` (873)

Risultato al 2026-10-07: 873 relazioni, 225 LEI.

| `period_end` (anno) | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 2032 |
|---|---|---|---|---|---|---|---|
| relazioni | 189 | 187 | 170 | 199 | 125 | 2 | 1 |

Con `period_end` = 31/12: 2024 → 159 LEI (157 con xBRL-JSON); 2025 → 104 LEI (102 con xBRL-JSON).

## 5. Problemi riscontrati nei dati dell'API

1. **Copertura parziale.** 102 LEI con xBRL-JSON per il 2025 sono molti meno degli emittenti di
   Euronext Milan soggetti a ESEF (ordine di grandezza 200+, da verificare). Mancano grandi emittenti:
   Intesa Sanpaolo non ha relazioni dopo il 2022; UniCredit, Enel, Leonardo, Poste, Snam e Terna
   non hanno il 2025. Il campione è quindi condizionato da ciò che filings.xbrl.org ha raccolto,
   non dall'universo CONSOB.
2. **`period_end` errato in 8 casi**, rilevati confrontandolo con la data nel nome del file JSON:
   Recordati `2032-12-31` (file 2022-12-31), Tenaris `2025-05-06` (file 2024-12-31),
   Juventus `2024-12-31` (file 2024-06-30), Fincantieri, Sogefi, Aquafil.
   Conseguenza: il periodo va ricavato dai fact (Passo 6), non dall'API. Il CSV dei candidati
   segnala il caso (`period_end_filename_mismatch`), senza correggerlo.
3. **Versioni multiple**: 140 coppie LEI × `period_end` hanno più di una relazione. Tipi osservati:
   - versioni in lingue diverse (it/en), stesso esercizio;
   - stessa lingua e **hash diversi** (possibile ri-deposito o ri-acquisizione: 54 relazioni
     risultano aggiunte lo stesso giorno, 2025-09-24, il che fa pensare a una ri-acquisizione
     massiva più che a correzioni dell'emittente — non verificabile dall'API);
   - stessa lingua e **stesso hash** (duplicati identici).
4. **Esercizi non solari** (31/01, 30/06, 30/09…): la convenzione per assegnare l'esercizio è ambigua.
5. Nomi file non uniformi (`<LEI>-<data>-it`, `<LEI>-<data>-0-it`, `moncler-<data>-0-IT`,
   `tim-<data>-it`, senza suffisso): l'indizio di lingua manca per 59 relazioni.

## 6. Punti non verificabili (decisione richiesta)

- Significato esatto di `sha256` (pacchetto? JSON?): verificabile solo dopo il download.
- Se una versione con `date_added` più recente sia una correzione dell'emittente o una
  ri-acquisizione della stessa relazione.
- Quale lingua considerare "ufficiale" quando esistono entrambe.
- Completezza della copertura italiana di filings.xbrl.org e criteri di raccolta.
