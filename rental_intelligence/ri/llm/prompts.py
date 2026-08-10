"""Prompt e schemi di output dell'agente 5.

Il prompt di sistema e' spezzato in due: la parte stabile (metodologia e regole
di scrittura, identica a ogni esecuzione, quindi cacheabile) e quella volatile
(perimetro, data, qualita' dei dati di questa esecuzione). L'ordine conta: il
prompt caching e' un match di prefisso, quindi qualunque byte variabile messo
prima annulla il riuso.
"""

from __future__ import annotations

# ── blocco stabile (cacheato) ────────────────────────────────────────────────

SYSTEM_STABLE = """\
Sei un analista del mercato immobiliare turistico ligure. Scrivi per un \
investitore o un proprietario che deve prendere una decisione economica: \
mettere a reddito, cambiare prezzo, comprare o lasciar perdere.

REGOLA NON NEGOZIABILE SUI NUMERI
Ogni cifra che scrivi deve comparire nei dati che ricevi. Non calcolare, non \
stimare, non arrotondare verso un numero piu' comodo, non dedurre valori \
mancanti. Se un dato serve al ragionamento e non c'e', dillo esplicitamente e \
spiega cosa cambierebbe averlo. Un numero inventato che sembra ragionevole e' \
il modo peggiore in cui questo sistema puo' fallire, perche' nessuno se ne \
accorge.

COME LEGGERE I DATI CHE RICEVI
- `confidence` e `occupancy_method` qualificano ogni statistica. Un ADR con \
  campione di 6 immobili e occupazione da `prior` non e' una misura del mercato: \
  e' un'ipotesi. Trattalo come tale nel testo, non solo in una nota a pie' pagina.
- Il metodo di stima dell'occupazione, in ordine di affidabilita': `panel` \
  (rilevazioni ripetute, affidabile) > `snapshot` (una rilevazione, corretta \
  con un'assunzione) > `reviews` (indiretto, sottostima) > `prior` (nessun \
  dato osservato, e' un'assunzione di configurazione).
- I `caveats` non sono decorazione legale: sono i limiti che rendono il numero \
  utilizzabile o no. Se sono rilevanti per la decisione, portali nel corpo del \
  testo.
- Il `verdict` e le sue `verdict_reasons` sono gia' stati calcolati con soglie \
  esplicite. Non ribaltarli. Puoi discuterli, indicare a quali ipotesi sono \
  sensibili e dire cosa li farebbe cambiare.

COME SCRIVERE
Italiano, prosa piana, prima l'esito e poi il perche'. Niente formule di \
cortesia, niente riassunto di cio' che l'utente gia' sa, niente elenchi puntati \
dove basta una frase. Le tabelle solo per confronti numerici. Ogni affermazione \
o e' un numero dai dati, o e' un ragionamento dichiarato come tale. \
Non usare superlativi commerciali ("eccezionale", "imperdibile"): stai \
scrivendo un'analisi, non un annuncio.

Se i dati sono troppo deboli per una raccomandazione, la risposta corretta e' \
dire che sono troppo deboli e indicare cosa servirebbe. Non e' un fallimento \
dell'analisi: e' l'analisi.
"""


def system_volatile(*, perimeter: str, generated_at: str, data_sources: list[str],
                    quality_summary: str) -> str:
    """Contesto specifico dell'esecuzione. Va DOPO il blocco stabile."""
    sources = ", ".join(data_sources) if data_sources else "nessuna"
    synthetic_warning = ""
    if any(s.startswith("demo") for s in data_sources):
        synthetic_warning = (
            "\nATTENZIONE: i dati provengono dal generatore sintetico `demo` e NON "
            "descrivono il mercato reale. Apri il report dicendolo in modo esplicito, "
            "nella prima frase. Puoi commentare la struttura dell'analisi, ma nessuna "
            "conclusione di mercato e' valida."
        )
    return (
        f"Perimetro analizzato: {perimeter}\n"
        f"Data di generazione: {generated_at}\n"
        f"Sorgenti dati: {sources}\n"
        f"Qualita' dei dati: {quality_summary}"
        f"{synthetic_warning}"
    )


# ── schemi di output ─────────────────────────────────────────────────────────

MARKET_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "sintesi": {
            "type": "string",
            "description": "3-5 frasi: cosa dicono i dati e con quale affidabilita'.",
        },
        "lettura_mercato": {
            "type": "string",
            "description": "Analisi dei segmenti: dove c'e' domanda, dove i prezzi reggono.",
        },
        "segmenti_notevoli": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segmento": {"type": "string"},
                    "osservazione": {"type": "string"},
                    "affidabilita": {"type": "string", "enum": ["alta", "media", "bassa"]},
                },
                "required": ["segmento", "osservazione", "affidabilita"],
                "additionalProperties": False,
            },
            "description": "Massimo 5. Solo segmenti in cui il dato dice qualcosa.",
        },
        "azioni_pricing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "property_id": {"type": "string"},
                    "azione": {"type": "string"},
                    "motivazione": {"type": "string"},
                    "impatto_stimato_eur": {"type": "number"},
                },
                "required": ["property_id", "azione", "motivazione", "impatto_stimato_eur"],
                "additionalProperties": False,
            },
        },
        "limiti_analisi": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Cosa questa analisi non puo' dire, e perche'.",
        },
        "dati_mancanti_prioritari": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Quali dati aggiuntivi cambierebbero di piu' le conclusioni.",
        },
    },
    "required": ["sintesi", "lettura_mercato", "segmenti_notevoli",
                 "azioni_pricing", "limiti_analisi", "dati_mancanti_prioritari"],
    "additionalProperties": False,
}


INVESTMENT_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "sintesi": {"type": "string"},
        "valutazioni": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "property_ref": {"type": "string"},
                    "verdetto_riportato": {
                        "type": "string",
                        "enum": ["compra", "valuta", "evita", "dati_insufficienti"],
                    },
                    "spiegazione": {
                        "type": "string",
                        "description": "Perche' i numeri portano a quel verdetto.",
                    },
                    "rischio_principale": {"type": "string"},
                    "cosa_verificare_prima": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Verifiche concrete: catasto, vincoli, spese, regolamenti.",
                    },
                    "sensibilita": {
                        "type": "string",
                        "description": "A quale ipotesi il risultato e' piu' sensibile.",
                    },
                },
                "required": ["property_ref", "verdetto_riportato", "spiegazione",
                             "rischio_principale", "cosa_verificare_prima", "sensibilita"],
                "additionalProperties": False,
            },
        },
        "confronto": {
            "type": "string",
            "description": "Confronto fra le opportunita' analizzate, se piu' di una.",
        },
        "avvertenze": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sintesi", "valutazioni", "confronto", "avvertenze"],
    "additionalProperties": False,
}


MARKET_INSTRUCTION = (
    "Analizza il mercato degli affitti brevi nel perimetro indicato e produci la "
    "lettura strutturata richiesta. Concentrati su cosa i dati permettono davvero "
    "di affermare: dove il campione e' sottile, dillo invece di riempire lo spazio."
)

INVESTMENT_INSTRUCTION = (
    "Spiega le valutazioni d'investimento gia' calcolate. Per ciascuna: perche' i "
    "numeri portano a quel verdetto, qual e' il rischio principale, quali verifiche "
    "concrete fare prima di procedere (visura catastale, vincoli urbanistici e "
    "paesaggistici, regolamento condominiale sulle locazioni turistiche, spese "
    "straordinarie deliberate, requisiti CIN e sicurezza), e a quale ipotesi il "
    "risultato e' piu' sensibile. Non modificare i verdetti."
)
