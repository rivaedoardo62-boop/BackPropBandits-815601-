# Note sull'API di filings.xbrl.org (Passo 2)

Verifica eseguita il **7 ottobre 2026** (UTC). Tutte le richieste sono partite
dal client del progetto (`src/extraction/sources/http.py`): User-Agent
descrittivo, almeno 1 s tra la fine di una richiesta e l'inizio della
successiva, nessuna credenziale.

Le richieste di prova sono ripetibili con:

```bash
python -m extraction verify-api --lei 815600115DA6E507AE33 --period-end 2025-12-31
```

Il comando scrive l'esito di ogni prova (URL esatto, stato HTTP, osservazioni)
in `data/interim/api_probe.json` ed esce con codice 1 se una prova non da'
piu' il risultato documentato qui. L'emittente di prova (Carel Industries) e'
uno dei venti proposti nel campione; la scelta non ha altro significato.

## 1. Cosa dice la documentazione

Fonte: <https://filings.xbrl.org/docs/api> (letta il 7/10/2026).

- L'API segue lo standard JSON:API ed e' raggiungibile su `https://filings.xbrl.org/api`.
- Risorse: `filing` (`/api/filings`), `entity` (`/api/entities`),
  `validation_message` (`/api/validation_messages`).
- Paginazione: `page[size]` e `page[number]`; i link alle altre pagine sono
  nell'oggetto `links` della risposta.
- Inclusione delle entita': `?include=entity`.
- Filtri semplici: `filter[<attributo>]=<valore>` (esempio della documentazione:
  `filter[country]=GB`). Filtri complessi con la sintassi della libreria
  Flask-COMBO-JSONAPI (<https://flask-combo-jsonapi.readthedocs.io/en/stable/filtering.html>):
  `filter=[{"name":..., "op":..., "val":...}]`, con `has` per le relazioni
  "a uno" e la forma abbreviata `relazione.attributo`.
- Ordinamento: `sort=<attributo>` (`-` per decrescente).
- La documentazione **non elenca gli attributi**: i nomi sotto sono stati
  ricavati dalle risposte reali.
- Condizioni d'uso: accesso gratuito, ma "we reserve the right to alter the API
  at any time, including applying rate limits or withdrawing it completely".
  Per uso regolare si raccomanda l'iscrizione alla mailing list.

## 2. Nomi reali verificati

| Informazione richiesta | Dove si trova | Verificato con |
|---|---|---|
| Paese | attributo filing `country` (es. `IT`); filtro `filter[country]=IT` | prova 1 |
| LEI | attributo entita' `identifier` (relazione `entity` del filing, da includere con `include=entity`) | prove 1, 3-6 |
| Nome entita' | attributo entita' `name` | prova 1 |
| Fine periodo | attributo filing `period_end` (`YYYY-MM-DD`) | prove 7-8 |
| Link xBRL-JSON | attributo filing `json_url` (percorso **relativo** all'host, puo' essere `null`) | prove 10, 13 |
| Link report package | attributo filing `package_url` (percorso relativo; estensione `.zip` o `.xbri`) | prove 11-12 |
| Data di aggiunta | attributo filing `date_added` (`YYYY-MM-DD hh:mm:ss[.ffffff]`, senza fuso orario) | prova 1 |
| Hash | attributo filing `sha256`: **SHA-256 del report package** (non dello xBRL-JSON) | prova 12 |
| Errori di validazione | attributi filing `error_count`, `warning_count`, `inconsistency_count` | prova 1 |
| Lingua | **non esposta dall'API** (ne' sul filing ne' sull'entita') | prova 1 |

Altri attributi del filing restituiti: `fxo_id`, `processed`, `report_url`,
`viewer_url`. Relazioni del filing: `entity`, `validation_messages`.
`fxo_id` ha la forma `<LEI>-<period_end>-ESEF-<paese>-<n>`, dove `<n>` numera
le relazioni multiple dello stesso emittente per lo stesso periodo.

## 3. Richieste di prova ed esito

Tutte con esito conforme a quanto sopra (13 richieste, 7/10/2026 07:24 UTC).
Gli URL sono riportati decodificati per leggibilita'; quelli esatti sono in
`data/interim/api_probe.json`.

| # | Richiesta | Esito |
|---|---|---|
| 1 | `GET /api/filings?filter[country]=IT&page[size]=2&include=entity` | 200; `meta.count=873`; attributi del filing e dell'entita' come in tabella; `links`: self, first, last, next |
| 2 | `GET /api/filings?filter[country]=IT&page[size]=5&sort=id` | 200; id in ordine numerico crescente (4, 31, 34, 115, 176): ordinamento stabile usato per la paginazione |
| 3 | `GET /api/filings?filter=[{"name":"entity","op":"has","val":{"name":"identifier","op":"eq","val":"815600115DA6E507AE33"}}]&include=entity` | 200; 5 relazioni, tutte con quel LEI |
| 4 | `GET /api/filings?filter=[{"name":"entity.identifier","op":"eq","val":"815600115DA6E507AE33"}]&include=entity` | 200; stesso risultato della prova 3 (forma abbreviata) |
| 5 | `GET /api/entities/815600115DA6E507AE33/filings` | 200; 5 relazioni (l'entita' e' indirizzabile per LEI) |
| 6 | `GET /api/entities/815600115DA6E507AE33` | 200; `{"name": "CAREL INDUSTRIES S.P.A.", "identifier": "815600115DA6E507AE33"}`, id interno 3433 |
| 7 | `GET /api/filings?filter[country]=IT&filter[period_end]=2025-12-31` | 200; 118 relazioni, tutte con `period_end` 2025-12-31 |
| 8 | `GET /api/filings?filter=[country eq IT, period_end ge 2025-01-01, period_end le 2025-12-31]` | 200; 125 relazioni tra 2025-01-31 e 2025-12-31 |
| 9 | `GET /api/filings?filter=[country eq IT, json_url is_ null]` | **400** "Bad filter value: None": i valori nulli non si possono filtrare lato server; le relazioni senza xBRL-JSON si individuano nell'elenco completo |
| 10 | `HEAD https://filings.xbrl.org/<json_url>` | 200; `application/json`, servito con `Content-Encoding: gzip` (302.681 byte compressi) |
| 11 | `HEAD https://filings.xbrl.org/<package_url>` | 200; `application/zip`, 5.854.521 byte |
| 12 | `GET` del pacchetto (hash calcolato in memoria, nulla salvato) | SHA-256 calcolato = attributo `sha256` dell'API (`719dbaa8...0ed6`) |
| 13 | `GET` dello xBRL-JSON (decompresso: 4.361.893 byte) | SHA-256 diverso da `sha256` dell'API: quell'attributo **non** riguarda il JSON |

I link `json_url`, `package_url`, `viewer_url` e `report_url` sono percorsi
relativi: l'URL assoluto si ottiene anteponendo `https://filings.xbrl.org`.
Il codice rifiuta qualsiasi link che punti a un host diverso.

### Formato dello xBRL-JSON (prova 13)

- `documentInfo.documentType` = `https://xbrl.org/2021/xbrl-json` (xBRL-JSON 1.0 dell'OIM).
- Chiavi di primo livello: `documentInfo`, `facts`. `documentInfo` contiene
  `documentType`, `features`, `namespaces`, `taxonomy` (punto di ingresso della
  tassonomia di estensione dell'emittente).
- `facts` e' un **dizionario indicizzato per id del fact** (es. `reg-ix-1`);
  ogni fact ha `value`, `dimensions` e, se numerico, `decimals`.
- `dimensions` contiene le dimensioni di base `concept`, `entity`, `period`,
  `unit`, `language` (fact testuali) e le dimensioni di tassonomia (es.
  `ifrs-full:ComponentsOfEquityAxis`): i fact "senza dimensioni aggiuntive"
  del Passo 6 saranno quelli che hanno solo dimensioni di base.
- Da verificare al Passo 6: se gli id dei fact nello xBRL-JSON coincidono con
  gli attributi `id` dell'iXBRL nel pacchetto (requisito di tracciabilita'),
  oppure se sono generati in fase di conversione.

## 4. Elenco completo delle relazioni italiane

```bash
python -m extraction filings-index --country IT
```

- Richieste: `GET /api/filings?filter[country]=IT&include=entity&page[size]=200&sort=id`
  seguendo `links.next` (5 pagine, 7/10/2026 07:19 UTC).
- Controlli: numero di record = `meta.count` (873), nessun id duplicato tra le
  pagine, attributi attesi presenti (se l'API rinomina un attributo il comando
  si ferma invece di scrivere colonne vuote), LEI con cifre di controllo
  ISO 17442 valide (873/873).
- Output: `data/interim/filings_it.csv` (una riga per relazione) e
  `data/interim/filings_it.meta.json` (provenienza: URL, ora, SHA-256 di ogni
  pagina). Le pagine originali restano in `data/raw/api/filings_it_<timestamp>/`.
- Colonne: `filing_id`, `fxo_id`, `lei`, `lei_checksum_ok`, `entity_name`,
  `country`, `period_end`, `language` (vuota: non fornita dall'API),
  `date_added`, `processed`, `sha256` (hash del pacchetto), `json_url`,
  `package_url`, `viewer_url`, `error_count`, `warning_count`,
  `inconsistency_count`, `snapshot_at`.

## 5. Problemi trovati nei metadati (snapshot del 7/10/2026)

- **873 relazioni, 225 entita'**. Per anno di fine periodo: 2021: 189, 2022: 187,
  2023: 170, 2024: 199, 2025: 125, 2026: 2, 2032: 1. La copertura del 2025 e'
  parziale: l'elenco non e' l'universo degli emittenti quotati.
- **9 relazioni senza xBRL-JSON** (`json_url` nullo), escluse dal campione.
- **Versioni multiple**: 140 coppie (LEI, `period_end`) hanno piu' relazioni.
  In 13 casi i pacchetti sono identici (stesso `sha256`, ricaricati); in 57 i
  nomi dei file differiscono (soprattutto versioni `-it`/`-en`); in 70 il nome
  del pacchetto e' lo stesso ma l'hash no. In questi ultimi il nome del file
  xBRL-JSON spesso distingue la lingua, ma in diversi casi (es. UniCredit
  2024: quattro versioni, due "it" e due "en") restano possibili sia versioni
  con perimetro diverso (consolidato/separato) sia rettifiche: dai soli
  metadati **non si puo' decidere**.
- **`period_end` incoerente con il nome del file** in 7 relazioni, ad esempio:
  Recordati con `period_end` 2032-12-31 e pacchetto "2022-12-31"; Fincantieri
  con una relazione `period_end` 2024-12-31 il cui pacchetto e' "2023-12-31"
  (aggiunta ad aprile 2024); Sogefi 2023-11-30 con pacchetto "2022-12-31";
  Tenaris 2025-05-06 con pacchetto "2024-12-31". Il periodo va ricontrollato
  sui contesti dei fact (Passo 6), non preso dai metadati.
- **Esercizi non solari** (es. OVS al 31/1, Juventus e S.S. Lazio al 30/6):
  esclusi dal campione per evitare ambiguita' su "esercizio 2024/2025".
- **Emittenti non di diritto italiano** nell'elenco IT (es. Brembo N.V., Ariston
  Holding N.V., Tenaris S.A., BB Biotech AG): il Paese dell'API non coincide
  necessariamente con lo Stato membro d'origine. Esclusi dal campione.
- **Nomi entita'**: sono quelli associati al LEI dall'API e possono non
  coincidere con la denominazione del gruppo quotato (es. "A2A ENERGIA S.P.A.").
  Va verificato su GLEIF prima di usare il nome in un report.
- **Formati del pacchetto**: dal 2024 compaiono pacchetti `.xbri` (36 tra 2024 e
  2025) oltre ai `.zip`; il download del Passo 4 deve gestire entrambi.
- **Errori di validazione**: 10 relazioni con `error_count` > 0 (nel 2024-2025:
  OVS 2025-01-31 e Zignago Vetro 2024).

## 6. Punti non verificabili (decisioni aperte)

- **Lingua della relazione**: l'API non la fornisce. Il suffisso `-it`/`-en`
  nel nome dei file e' una convenzione, non un dato: nel campione e' usato solo
  come indizio (`lang_hint_filename`). Proposta: dopo il download, determinarla
  dal contenuto (dimensione `language` dei fact testuali nello xBRL-JSON).
- **Versione da usare quando i metadati non bastano**: proposta di scaricare
  tutte le versioni e confrontarle sui fact (vedi `src/extraction/sample.py`).
- **Origine dei dati di filings.xbrl.org** (da quali meccanismi di stoccaggio o
  canali vengono raccolte le relazioni italiane) e criteri di aggiornamento:
  non documentati nella pagina dell'API.
