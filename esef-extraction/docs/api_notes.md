# Note sull'API di filings.xbrl.org e sul formato xBRL-JSON

Verifiche eseguite il **2026-10-07**. Ogni affermazione indica la richiesta o il documento
da cui deriva. Ciò che non è stato possibile verificare è nella sezione 7.

## 1. Fonti consultate

| Fonte | Uso |
|---|---|
| https://filings.xbrl.org/docs/api | documentazione ufficiale dell'API |
| https://flask-combo-jsonapi.readthedocs.io/en/stable/filtering.html | sintassi dei filtri complessi (link presente nella documentazione ufficiale) |
| https://www.xbrl.org/Specification/xbrl-json/REC-2021-10-13/xbrl-json-REC-2021-10-13.html | specifica xBRL-JSON |
| https://www.xbrl.org/Specification/oim/REC-2021-10-13/oim-REC-2021-10-13.html | modello OIM (dimensione periodo) |
| https://www.xbrl.org/Specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html | §4.7.2, convenzione "fine giornata" delle date |

## 2. Cosa dice la documentazione ufficiale

- API conforme a **JSON:API**, base `https://filings.xbrl.org/api`.
- Risorse: `filing` (`/api/filings`), `entity` (`/api/entities`), `validation_message` (`/api/validation_messages`).
- Paginazione: `page[size]`, `page[number]`; i link alle altre pagine sono in `links` (`first`, `last`, `next`).
- `include=entity` aggiunge le entità collegate nella sezione `included`.
- Filtri semplici `filter[<attributo>]=<valore>` (solo uguaglianza); filtri complessi con
  `filter=[{"name": ..., "op": ..., "val": ...}]` secondo la sintassi flask-combo-jsonapi
  (operatori `eq`, `ge`, `le`, `in_`, `has`, `any`, ...; scorciatoia `relazione.attributo`).
- Ordinamento con `sort` (prefisso `-` per decrescente).
- Avvertenza dell'API: accesso gratuito ma l'API può cambiare, essere limitata (rate limit) o ritirata
  in qualunque momento. Non sono documentati limiti di frequenza: il client usa comunque ≥ 1 s tra
  le richieste (default 1,5 s) e un User-Agent descrittivo.

## 3. Richieste di prova e risultati

Tutte con User-Agent `esef-extraction/0.1.0 (research prototype; ESEF financial indicator extraction)`
e almeno 1 s tra una richiesta e l'altra.

| # | Richiesta (decodificata) | Esito | Cosa verifica |
|---|---|---|---|
| 1 | `GET /api/filings?filter[country]=IT&page[size]=2&include=entity` | 200, `meta.count`=873 | nome del filtro Paese, attributi della relazione, struttura di `included` |
| 2 | `GET /api/filings/6710` | 200 | stessi attributi sulla singola risorsa |
| 3 | `GET /api/entities/8156001A772766DCAA71` | 200 | attributi dell'entità: `name`, `identifier` (= LEI) |
| 4 | `GET /api/entities?page[size]=2` | 200, `meta.count`=7365 | l'elenco entità copre tutti i Paesi |
| 5 | `GET /api/filings?filter=[{"name":"country","op":"eq","val":"IT"},{"name":"period_end","op":"ge","val":"2024-01-01"}]&sort=-period_end&page[size]=3` | 200, 327 risultati | filtro sulla data di fine periodo, ordinamento |
| 6 | `GET /api/filings?filter=[{"name":"entity.identifier","op":"eq","val":"8156001A772766DCAA71"}]` | 200, 5 risultati | filtro per LEI (scorciatoia sulla relazione) |
| 7 | come 6 con `{"name":"entity","op":"has","val":{"name":"identifier","op":"eq","val":"..."}}` | 200, stessi 5 risultati | filtro per LEI (forma esplicita) |
| 8 | `GET /api/filings?filter[country]=IT&page[size]=500` | 200, 500 elementi | `page[size]=500` accettato (il client usa 200) |
| 9 | elenco completo: `GET /api/filings?filter[country]=IT&page[size]=200&include=entity&sort=id`, poi `links.next` | 5 pagine, 873 relazioni = `meta.count` | Passo 2; `sort=id` rende stabile la paginazione |

### Download di prova (solo verifica del formato)

Per capire il formato e il significato delle versioni multiple sono stati scaricati **7 file**
da filings.xbrl.org, salvati in una cartella temporanea **fuori dal repository** e **non usati
dalla pipeline** (il download vero è il Passo 4, dopo l'approvazione del campione):

| File | Esito |
|---|---|
| Prysmian FY2024, xBRL-JSON versione 0 (`...-2024-12-31-en.json`) e versione 1 (`...-it.json`) | 554 fact ciascuno; 240 chiavi numeriche senza dimensioni, **nessuna differenza di valore** tra EN e IT |
| Prysmian FY2024, pacchetto versione 1 (`.zip`, 14,8 MB) | SHA-256 del file = attributo `sha256` dell'API → **`sha256` è l'hash del report package** |
| Banca MPS FY2024, xBRL-JSON versioni 0 e 1 (75–79 MB l'uno) | stessa lingua, hash del pacchetto diversi, 275 chiavi numeriche **identiche** |
| De' Longhi FY2025, xBRL-JSON versioni 0 e 1 | 229 chiavi numeriche **identiche**; ma i fact testuali della versione 0 sono in inglese pur essendo marcati `it` |

## 4. Attributi verificati e corrispondenza con le colonne richieste

Attributi della risorsa `filing`: `fxo_id`, `country`, `period_end`, `date_added`, `processed`, `sha256`,
`json_url`, `package_url`, `report_url`, `viewer_url`, `error_count`, `warning_count`, `inconsistency_count`.
Gli URL sono **percorsi relativi** a `https://filings.xbrl.org`. Attributi di `entity`: `name`, `identifier`.

| Colonna richiesta | Campo API | Note |
|---|---|---|
| entità | `entity.name` (via `include=entity`) | è la denominazione registrata, spesso lunga (es. "TELECOM ITALIA SPA O TIM S.P.A.") |
| LEI | `entity.identifier` | coincide con il prefisso di `fxo_id` in 873/873 casi |
| fine periodo | `period_end` | **non sempre affidabile**, vedi §6.1 |
| lingua | **non disponibile** | vedi §6.3: in `filings_it.csv` c'è `language_hint`, suffisso del nome file, non verificato |
| data di aggiunta | `date_added` | |
| hash | `sha256` | SHA-256 del report package (verificato) |
| link xBRL-JSON | `json_url` | assente in 9 relazioni IT |
| link pacchetto | `package_url` | estensione `.zip` o `.xbri` (36 casi `.xbri` negli esercizi 2024-2025) |
| errori di validazione | `error_count` | disponibili anche `warning_count`, `inconsistency_count` |

`fxo_id` ha la forma `<LEI>-<period_end>-ESEF-<Paese>-<n>`: `<n>` (colonna `fxo_seq`) numera le
relazioni con stesso LEI e stesso `period_end`. Il formato è osservato, non documentato.

## 5. Formato xBRL-JSON e report package (verificato sui file di prova)

- Oggetto radice: `documentInfo` (con `documentType` = `https://xbrl.org/2021/xbrl-json`, `namespaces`,
  `taxonomy`) e `facts`.
- `facts` è un dizionario `id del fact → {value, decimals, dimensions, links?}`. **La chiave è l'`@id` del
  fact nel documento iXBRL**: 554/554 chiavi ritrovate come `id` nell'`.xhtml` del pacchetto Prysmian.
  È quindi l'identificativo da usare come `source_fact_id`. Gli id possono superare i 300 caratteri.
- `value` è una stringa (forma canonica, es. `"4921000000.0"`); `decimals` è un intero (es. `-6`).
- `dimensions` contiene le dimensioni "core" `concept`, `entity` (`scheme:<LEI>`), `period`, `unit`
  (es. `iso4217:EUR`), `language` (solo fact testuali) e le dimensioni di tassonomia
  (es. `ifrs-full:ComponentsOfEquityAxis`). Un fact "senza dimensioni aggiuntive" è quindi un fact
  senza chiavi diverse da `concept`, `entity`, `period`, `unit`, `language`.
- Le note a piè di pagina sono fact con `concept` = `xbrl:note` e chiave `noteId`, senza entità né periodo:
  vanno escluse dall'estrazione.
- **Convenzione delle date** (XBRL 2.1 §4.7.2 e esempi della specifica xBRL-JSON): una data di fine o un
  istante senza ora indica la fine della giornata e in xBRL-JSON diventa la mezzanotte del giorno dopo.
  Quindi il 31/12/2024 è `"2025-01-01T00:00:00"` e l'esercizio 2024 è
  `"2024-01-01T00:00:00/2025-01-01T00:00:00"`. Verificato sui dati (Prysmian, MPS, De' Longhi). L'estrattore
  dovrà sottrarre un giorno a istanti e date di fine con ora `00:00:00`.
- Report package: cartella radice con `META-INF/taxonomyPackage.xml` e `catalog.xml`, tassonomia di
  estensione (`.xsd`, `_cal.xml`, `_def.xml`, `_pre.xml`, `_lab-it.xml`, `_lab-en.xml`) e `reports/*.xhtml`
  con `xml:lang` sulla radice. **Le etichette dei concetti di estensione non sono nello xBRL-JSON**: per
  cercare "EBITDA" nelle etichette serve il label linkbase contenuto nel pacchetto.

## 6. Problemi trovati nei dati

### 6.1 `period_end` dell'API non sempre corrisponde al periodo della relazione

In 8 relazioni IT la data nel nome del file contraddice `period_end` (colonna `period_end_matches_filename`):

| Emittente | `period_end` API | data nel nome file |
|---|---|---|
| Recordati | 2032-12-31 | 2022-12-31 |
| Fincantieri | 2024-12-31 | 2023-12-31 |
| Juventus FC | 2024-12-31 | 2024-06-30 |
| Aquafil | 2023-12-31 | 2022-12-31 |
| Sogefi | 2023-11-30 | 2022-12-31 |
| Tenaris (3 relazioni) | 2024-04-30, 2025-05-06 | 2023-12-31, 2024-12-31 |

Per 2 relazioni Saipem (2021, 2022) i nomi dei file non contengono una data: il controllo non è possibile.
Ne segue che un filtro sull'esercizio basato solo su `period_end` può assegnare una relazione
all'esercizio sbagliato. Il periodo effettivo va verificato sui fact dopo il download.
Come `period_end` sia calcolato da filings.xbrl.org non è documentato.

### 6.2 Più relazioni per lo stesso emittente e periodo

Negli esercizi 2024-2025, 45 coppie LEI/periodo hanno più relazioni. Tre tipi osservati:
1. **versioni linguistiche** (suffisso `-it` / `-en`): valori numerici identici nel caso verificato (Prysmian);
2. **stessa lingua, pacchetti diversi**, spesso con una seconda ondata di aggiunte il 2025-09-24: valori numerici
   identici nei due casi verificati (MPS 2024, De' Longhi 2025), ma testo diverso;
3. **pacchetti identici** (stesso `sha256`), cioè la stessa relazione indicizzata due volte (IGD, PLC, Ferragamo, Tenaris).

Due verifiche non bastano per concludere che le versioni dello stesso esercizio abbiano sempre gli stessi
numeri: la pipeline dovrà confrontarle dopo il download.

### 6.3 La lingua non è esposta dall'API

Il suffisso del nome file (`language_hint`) è scelto dall'emittente: in De' Longhi FY2025 entrambe le
versioni hanno suffisso `-it` ma una è in inglese, e i suoi fact testuali sono comunque marcati `it`.
Né il nome file né `xml:lang` garantiscono la lingua effettiva.

### 6.4 Copertura dell'esercizio 2025

Relazioni IT per anno di `period_end`: 2021: 189, 2022: 187, 2023: 170, **2024: 199 (165 emittenti),
2025: 125 (110 emittenti)**. L'ultima `date_added` è 2026-10-06: l'indice è ancora in aggiornamento e
la copertura del 2025 è sensibilmente più bassa. Il campione è quindi condizionato da ciò che è già
indicizzato; non è noto se manchino relazioni depositate.

### 6.5 Altre osservazioni utili per i passi successivi

- De' Longhi FY2025 non usa `ifrs-full:Revenue` ma `ifrs-full:RevenueFromContractsWithCustomers` e
  `ifrs-full:RevenueAndOperatingIncome`: con il solo concetto indicato per REVENUE l'indicatore risulterebbe
  mancante.
- MPS FY2024 non ha né `ifrs-full:Revenue` né `ifrs-full:Equity` tra i fact senza dimensioni: per banche e
  assicurazioni molti indicatori saranno strutturalmente non applicabili.
- Un emittente registrato come "A2A ENERGIA S.P.A." ha 4 relazioni FY2024: la denominazione andrebbe
  controllata rispetto alla capogruppo quotata (non verificato, emittente non incluso nel campione).

## 7. Non verificato / da decidere

- **Lingua**: l'API non la fornisce; proposta: determinarla dopo il download dai fact testuali e segnalare
  le incoerenze con il nome file. Serve una decisione su quale versione considerare ufficiale (proposta: italiana).
- Algoritmo con cui l'API calcola `period_end` e significato preciso di `processed`.
- Natura delle versioni con la stessa lingua e hash diverso (ri-deposito, correzione o re-indicizzazione):
  non ricavabile dall'API.
- Limiti di frequenza: non documentati e non osservati (nessun 429 nelle prove).
