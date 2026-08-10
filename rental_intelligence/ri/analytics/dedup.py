"""Entity resolution: capire quando due annunci sono lo stesso immobile.

Questo e' il problema tecnico piu' difficile del progetto, e quello che la
richiesta iniziale non prevedeva. Va detto chiaramente perche' conta: senza
deduplica, un mercato con il 30% di annunci multi-piattaforma sembra avere il
30% di offerta in piu' di quella reale, e ogni percentile di prezzo che calcoli
sopra e' distorto. Il numero sbagliato non e' "un po' impreciso": e'
sistematicamente sbagliato nella stessa direzione.

Perche' e' difficile:
  - le coordinate sono volutamente offuscate (~100-200 m) dalle piattaforme;
  - i titoli sono riscritti da zero per ogni canale;
  - la capienza dichiarata differisce (divano letto contato o no);
  - le foto sono le stesse ma ritagliate diversamente;
  - non esiste una chiave comune... tranne una.

Quella eccezione e' il CIN (Codice Identificativo Nazionale). Dove e' esposto,
due annunci con lo stesso codice sono la stessa unita' immobiliare per
definizione normativa: il problema collassa da inferenza statistica a join
esatto. È il motivo per cui il connettore verso il registro CIN vale piu' di
qualunque ottimizzazione del punteggio qui sotto.

Strategia:
  1. blocking: confronta solo coppie plausibili (stesso comune, capienza vicina).
     Senza blocking il costo e' O(n²) e a 50k annunci non finisce piu'.
  2. match esatto su CIN -> fusione immediata, confidenza 1.0.
  3. altrimenti punteggio pesato su piu' segnali indipendenti.
  4. clustering con union-find sulle coppie sopra soglia.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .. import geo
from ..models import Listing, ListingIntent, Property, PropertyType

# Parole che compaiono in quasi tutti i titoli e non distinguono nulla:
# tenerle gonfia la similarita' fra annunci completamente diversi.
_STOPWORDS = {
    "a", "al", "alla", "con", "da", "di", "e", "il", "in", "la", "lo", "per",
    "un", "una", "the", "with", "and", "for", "appartamento", "apartment",
    "casa", "house", "flat", "ospiti", "guests", "camera", "room", "affitto",
    "vacanze", "holiday", "mare", "sea", "centro", "vista", "view", "nuovo",
    "bellissimo", "splendido", "accogliente", "luminoso", "grazioso",
}

# Pesi dei segnali. Somma dei pesi usati -> normalizzazione, cosi' un segnale
# assente non penalizza la coppia (assenza != disaccordo).
WEIGHTS = {
    "geo": 0.34,
    "capacity": 0.16,
    "bedrooms": 0.10,
    "title": 0.18,
    "amenities": 0.12,
    "surface": 0.06,
    "host": 0.04,
}

MATCH_THRESHOLD = 0.62
GEO_TOLERANCE_M = 220.0     # copre l'offuscamento tipico delle OTA

# Numero minimo di segnali FORTI e indipendenti richiesti per fondere due
# annunci in assenza di CIN.
#
# Serve perche' il punteggio pesato, da solo, non regge nei centri storici
# liguri. A Vernazza o a Portofino centinaia di annunci stanno in poche
# centinaia di metri, hanno la stessa capienza, gli stessi servizi standard e
# titoli quasi identici: geografia e attributi smettono di essere
# discriminanti. Un punteggio alto costruito su quei segnali dice "sono due
# bilocali in centro", non "sono lo stesso bilocale".
#
# La regola e' quindi asimmetrica di proposito: preferisce non fondere. Un
# duplicato non riconosciuto gonfia leggermente il conteggio dell'offerta; una
# fusione sbagliata cancella un immobile reale dal mercato e sposta tutti i
# percentili. Il secondo errore e' piu' grave e molto piu' difficile da notare.
CORROBORATION_MIN = 2


# ── normalizzazioni ──────────────────────────────────────────────────────────

def normalize_licence(code: str | None) -> Optional[str]:
    """CIN/CIR confrontabile: maiuscolo, senza separatori ne' spazi."""
    if not code:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(code)).upper()
    return cleaned or None


def title_tokens(title: str | None, comune: str | None = None) -> set[str]:
    """Token distintivi di un titolo.

    Il nome del comune viene rimosso: dentro un blocco di confronto tutti gli
    annunci stanno nello stesso comune, quindi quel token compare ovunque e non
    distingue nulla — anzi, gonfia la somiglianza fra immobili diversi. Con
    titoli poveri ("Trilocale a Vernazza" vs "Trilocale a Vernazza") bastava a
    portare la Jaccard a 1.0 su due appartamenti che non hanno niente in comune.
    """
    if not title:
        return set()
    tokens = {t for t in geo.normalize_place(title).split()
              if len(t) > 2 and t not in _STOPWORDS}
    if comune:
        tokens -= set(geo.normalize_place(comune).split())
    return tokens


def jaccard(a: set, b: set) -> Optional[float]:
    if not a or not b:
        return None
    union = a | b
    return len(a & b) / len(union) if union else None


# ── punteggio ────────────────────────────────────────────────────────────────

@dataclass
class MatchScore:
    score: float
    evidence: list[str] = field(default_factory=list)
    exact_licence: bool = False
    strong_signals: list[str] = field(default_factory=list)

    def is_match(self, threshold: float = MATCH_THRESHOLD) -> bool:
        """Fusione ammessa: CIN identico, oppure punteggio sopra soglia *e*
        almeno `CORROBORATION_MIN` segnali forti indipendenti."""
        if self.exact_licence:
            return True
        return self.score >= threshold and len(self.strong_signals) >= CORROBORATION_MIN


def score_pair(a: Listing, b: Listing) -> MatchScore:
    """Punteggio di somiglianza in [0, 1] fra due annunci.

    Ogni segnale puo' restituire None (dato mancante da almeno un lato): in quel
    caso viene escluso sia dal numeratore sia dal denominatore. Un annuncio
    povero di metadati ottiene cosi' un punteggio basato su cio' che si sa,
    invece di essere penalizzato per cio' che non si sa.
    """
    lic_a, lic_b = normalize_licence(a.licence_code), normalize_licence(b.licence_code)
    if lic_a and lic_b:
        if lic_a == lic_b:
            return MatchScore(1.0, [f"CIN identico ({lic_a})"], exact_licence=True,
                              strong_signals=["licence"])
        # Due CIN diversi sono prova positiva di immobili diversi: e' l'unico
        # segnale che puo' da solo escludere una coppia.
        return MatchScore(0.0, [f"CIN diversi ({lic_a} != {lic_b})"])

    signals: dict[str, Optional[float]] = {}
    evidence: list[str] = []
    strong: list[str] = []

    signals["geo"] = geo.geo_similarity(a.lat, a.lon, b.lat, b.lon, GEO_TOLERANCE_M)
    if signals["geo"] is not None and a.lat is not None and b.lat is not None:
        dist = geo.haversine_m(a.lat, a.lon, b.lat, b.lon)  # type: ignore[arg-type]
        evidence.append(f"distanza {dist:.0f} m")
        if dist <= 120:
            strong.append("geo")

    if a.max_guests and b.max_guests:
        delta = abs(a.max_guests - b.max_guests)
        signals["capacity"] = {0: 1.0, 1: 0.7, 2: 0.25}.get(delta, 0.0)
        evidence.append(f"capienza {a.max_guests} vs {b.max_guests}")

    if a.bedrooms is not None and b.bedrooms is not None:
        signals["bedrooms"] = 1.0 if a.bedrooms == b.bedrooms else (
            0.5 if abs(a.bedrooms - b.bedrooms) == 1 else 0.0)

    tok_a = title_tokens(a.title, a.comune)
    tok_b = title_tokens(b.title, b.comune)
    t = jaccard(tok_a, tok_b)
    if t is not None:
        signals["title"] = t
        # Una Jaccard alta su titoli poverissimi non e' evidenza: "Trilocale"
        # contro "Trilocale" da' 1.00 e descrive meta' del patrimonio edilizio
        # ligure. Perche' il titolo valga come segnale forte servono abbastanza
        # token distintivi da entrambi i lati.
        if t >= 0.45 and min(len(tok_a), len(tok_b)) >= 3:
            evidence.append(f"titoli molto simili (Jaccard {t:.2f}, "
                            f"{min(len(tok_a), len(tok_b))} token)")
            strong.append("title")

    am = jaccard(set(a.amenities), set(b.amenities))
    if am is not None:
        signals["amenities"] = am

    if a.surface_sqm and b.surface_sqm:
        rel = abs(a.surface_sqm - b.surface_sqm) / max(a.surface_sqm, b.surface_sqm)
        signals["surface"] = max(0.0, 1.0 - rel / 0.20)   # 20% di scarto -> 0
        if rel <= 0.05:
            evidence.append(f"superficie quasi identica ({a.surface_sqm} / {b.surface_sqm} mq)")
            strong.append("surface")

    if a.host_key and b.host_key:
        same_host = a.host_key == b.host_key
        signals["host"] = 1.0 if same_host else 0.0
        if same_host:
            evidence.append("stesso host")
            strong.append("host")

    used = {k: v for k, v in signals.items() if v is not None}
    if not used:
        return MatchScore(0.0, ["nessun segnale confrontabile"])

    total_w = sum(WEIGHTS[k] for k in used)
    score = sum(WEIGHTS[k] * v for k, v in used.items()) / total_w
    return MatchScore(round(score, 4), evidence, strong_signals=strong)


# ── union-find ───────────────────────────────────────────────────────────────

class _UnionFind:
    """Union-find con vincolo di esclusivita' per sorgente.

    Il vincolo esiste per chiudere una falla che il solo confronto a coppie non
    puo' vedere: la **chiusura transitiva**. Se A~B e B~C, union-find fonde
    anche A e C, anche quando A e C sono chiaramente immobili diversi. Nel
    nostro caso A e C finivano per essere due annunci della stessa piattaforma,
    cioe' proprio la coppia che il confronto diretto si rifiuta di valutare.

    La regola aggiuntiva e' semplice e viene dal dominio: **un immobile e'
    normalmente pubblicato al massimo una volta per piattaforma.** Un cluster
    che conterrebbe due annunci Airbnb distinti e' quindi malformato, e la
    fusione che lo produrrebbe va rifiutata invece che accettata.

    Unica eccezione: il CIN. Se due annunci della stessa piattaforma espongono
    lo stesso codice identificativo, e' un dato di fatto normativo e vince sul
    vincolo euristico.
    """

    def __init__(self, items: dict[str, str]) -> None:
        self.parent = {i: i for i in items}
        self.sources: dict[str, set[str]] = {i: {src} for i, src in items.items()}
        self.rejected_by_constraint = 0

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str, *, force: bool = False) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if not force and self.sources[ra] & self.sources[rb]:
            self.rejected_by_constraint += 1
            return False
        self.parent[rb] = ra
        self.sources[ra] |= self.sources[rb]
        return True


# ── deduplica ────────────────────────────────────────────────────────────────

def deduplicate(
    listings: list[Listing],
    *,
    threshold: float = MATCH_THRESHOLD,
) -> tuple[list[Property], dict]:
    """Raggruppa gli annunci di affitto breve in immobili fisici.

    Gli annunci di vendita restano volutamente fuori: un immobile in vendita e
    lo stesso immobile affittato sono la stessa unita' fisica ma due eventi di
    mercato diversi, e fonderli distruggerebbe l'analisi. Il collegamento fra i
    due mondi lo fa l'agente 3 tramite il segmento di mercato.
    """
    short_lets = [l for l in listings if l.intent is ListingIntent.SHORT_LET]
    if not short_lets:
        return [], {"n_input": 0, "n_properties": 0, "n_pairs_evaluated": 0}

    by_id = {l.listing_id: l for l in short_lets}
    uf = _UnionFind({l.listing_id: l.source for l in short_lets})
    evidence_log: dict[tuple[str, str], MatchScore] = {}

    # 1. Chiave forte: fusione diretta su CIN. `force=True` perche' il codice
    #    identificativo batte l'euristica dell'esclusivita' per piattaforma.
    by_licence: dict[str, list[str]] = defaultdict(list)
    for l in short_lets:
        code = normalize_licence(l.licence_code)
        if code:
            by_licence[code].append(l.listing_id)
    n_licence_merges = 0
    for code, ids in by_licence.items():
        for other in ids[1:]:
            if uf.union(ids[0], other, force=True):
                evidence_log[(ids[0], other)] = MatchScore(
                    1.0, [f"CIN identico ({code})"], True, ["licence"])
                n_licence_merges += 1

    # 2. Blocking: (comune, bucket capienza) e bucket adiacenti.
    blocks: dict[tuple[str, str], list[str]] = defaultdict(list)
    for l in short_lets:
        comune = l.comune or l.macro_market or "?"
        blocks[(comune, geo.capacity_bucket(l.max_guests))].append(l.listing_id)

    bucket_order = ["1-2", "3-4", "5-6", "7+", "sconosciuta"]
    pairs_evaluated = 0
    n_score_merges = 0
    n_near_misses = 0
    candidate_pairs: list[tuple[float, str, str, MatchScore]] = []

    for (comune, bucket), ids in blocks.items():
        candidates = list(ids)
        # I bucket adiacenti vanno inclusi: la capienza dichiarata e' proprio
        # uno dei campi che le piattaforme riportano diversamente.
        if bucket in bucket_order:
            idx = bucket_order.index(bucket)
            if idx + 1 < len(bucket_order):
                candidates += blocks.get((comune, bucket_order[idx + 1]), [])

        for i, id_a in enumerate(candidates):
            for id_b in candidates[i + 1:]:
                a, b = by_id[id_a], by_id[id_b]
                if a.source == b.source:
                    # Due annunci sulla stessa piattaforma sono in genere due
                    # unita' distinte dello stesso stabile. Fonderli e' un
                    # errore piu' costoso del non fonderli.
                    continue
                pairs_evaluated += 1
                result = score_pair(a, b)
                if result.is_match(threshold):
                    candidate_pairs.append((result.score, id_a, id_b, result))
                elif result.score >= threshold:
                    # Punteggio alto ma corroborazione insufficiente: e' il
                    # caso tipico del centro storico denso. Contarlo serve a
                    # capire quanto la regola sta trattenendo.
                    n_near_misses += 1

    # 3. Fusione in ordine di punteggio decrescente.
    #    L'ordine conta perche' il vincolo di esclusivita' per sorgente rende
    #    le fusioni mutuamente esclusive: se un annuncio Booking e' compatibile
    #    con due annunci Airbnb, ne puo' scegliere uno solo, e deve essere
    #    quello con l'evidenza piu' forte. Processare le coppie nell'ordine in
    #    cui capitano darebbe un risultato dipendente dall'ordinamento
    #    dell'input, cioe' non riproducibile.
    for score, id_a, id_b, result in sorted(candidate_pairs, key=lambda p: -p[0]):
        if uf.union(id_a, id_b):
            evidence_log[(id_a, id_b)] = result
            n_score_merges += 1

    # 4. Materializza i cluster.
    clusters: dict[str, list[str]] = defaultdict(list)
    for listing_id in by_id:
        clusters[uf.find(listing_id)].append(listing_id)

    properties: list[Property] = []
    for root, members in clusters.items():
        members_sorted = sorted(members)
        items = [by_id[m] for m in members_sorted]
        ev: list[str] = []
        conf = 1.0
        for (x, y), result in evidence_log.items():
            if x in members_sorted and y in members_sorted:
                ev.extend(result.evidence)
                conf = min(conf, 1.0 if result.exact_licence else result.score)

        properties.append(Property(
            property_id=f"prop-{root}",
            listing_ids=members_sorted,
            sources=sorted({i.source for i in items}),
            comune=_mode([i.comune for i in items]),
            macro_market=_mode([i.macro_market for i in items]),
            lat=_mean([i.lat for i in items]),
            lon=_mean([i.lon for i in items]),
            property_type=_mode([i.property_type for i in items]) or PropertyType.UNKNOWN,
            max_guests=_max([i.max_guests for i in items]),
            bedrooms=_max([i.bedrooms for i in items]),
            licence_code=next((normalize_licence(i.licence_code) for i in items
                               if i.licence_code), None),
            merge_evidence=ev[:8],
            merge_confidence=round(conf, 4) if len(members_sorted) > 1 else 1.0,
        ))

    meta = {
        "n_input": len(short_lets),
        "n_properties": len(properties),
        "n_pairs_evaluated": pairs_evaluated,
        "n_licence_merges": n_licence_merges,
        "n_score_merges": n_score_merges,
        "n_near_misses": n_near_misses,
        "n_rejected_source_conflict": uf.rejected_by_constraint,
        "corroboration_min": CORROBORATION_MIN,
        "dedup_ratio": round(1 - len(properties) / len(short_lets), 4),
        "threshold": threshold,
        "licence_coverage": round(
            sum(1 for l in short_lets if normalize_licence(l.licence_code)) / len(short_lets), 4
        ),
    }
    return sorted(properties, key=lambda p: p.property_id), meta


# ── piccoli aggregatori tolleranti ai None ───────────────────────────────────

def _mode(values: list):
    counts: dict = defaultdict(int)
    for v in values:
        if v is not None:
            counts[v] += 1
    return max(counts, key=counts.get) if counts else None


def _mean(values: list) -> Optional[float]:
    nums = [v for v in values if v is not None and not math.isnan(v)]
    return round(sum(nums) / len(nums), 6) if nums else None


def _max(values: list):
    nums = [v for v in values if v is not None]
    return max(nums) if nums else None
