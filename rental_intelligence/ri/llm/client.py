"""Client Claude per l'agente 5.

Scelte di progetto, tutte nella stessa direzione — impedire al modello di
inventare numeri:

* **Il modello non calcola nulla.** Riceve una scheda-fatti gia' calcolata da
  `analytics/` e la commenta. Se gli si chiedesse di derivare un rendimento,
  prima o poi ne produrrebbe uno plausibile e sbagliato, indistinguibile da uno
  giusto.
* **Output strutturato.** La risposta e' vincolata a uno schema JSON, quindi il
  chiamante non fa parsing di testo libero e non c'e' un formato da negoziare.
* **Degradazione controllata.** Senza chiave o con `RI_LLM_ENABLED=false` il
  sistema produce lo stesso report da template. L'LLM aggiunge leggibilita',
  non e' un ingranaggio strutturale.
* **Prompt caching** sul blocco metodologico, che e' identico fra le chiamate.
* **Fallback lato server abilitato** (`fallbacks="default"`): se i classificatori
  di sicurezza rifiutano una richiesta, l'API la riesegue automaticamente su un
  modello di ripiego invece di restituire un buco.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .. import config

logger = logging.getLogger(__name__)

# Beta necessarie: `fallbacks="default"` richiede questo header esatto.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(RuntimeError):
    """L'LLM non e' utilizzabile: chiave assente, SDK mancante o disattivato."""


class LLMRefused(RuntimeError):
    """La richiesta e' stata declinata dai classificatori di sicurezza."""


class ClaudeClient:
    """Wrapper sottile attorno all'SDK Anthropic."""

    def __init__(
        self,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> None:
        if not config.llm_enabled():
            raise LLMUnavailable("RI_LLM_ENABLED non attivo")
        if not config.anthropic_api_key():
            raise LLMUnavailable("ANTHROPIC_API_KEY non impostata")

        try:
            import anthropic  # import ritardato: dipendenza opzionale
        except ImportError as exc:
            raise LLMUnavailable(
                "pacchetto `anthropic` non installato "
                "(pip install -r rental_intelligence/requirements.txt)"
            ) from exc

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key())
        self.model = model or config.llm_model()
        self.effort = effort or config.llm_effort()
        self.max_tokens = max_tokens
        self.usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    # ── chiamata strutturata ─────────────────────────────────────────────────

    def generate_structured(
        self,
        *,
        system_stable: str,
        system_volatile: str = "",
        user_payload: dict[str, Any],
        json_schema: dict[str, Any],
        instruction: str,
    ) -> dict[str, Any]:
        """Una chiamata, risposta vincolata a `json_schema`.

        `system_stable` va per primo e porta il breakpoint di cache: e' il
        blocco identico fra tutte le chiamate (metodologia, regole di
        scrittura). `system_volatile` viene dopo ed e' escluso dalla cache.
        Invertire i due annullerebbe ogni riuso.
        """
        system_blocks: list[dict[str, Any]] = [{
            "type": "text",
            "text": system_stable,
            "cache_control": {"type": "ephemeral"},
        }]
        if system_volatile:
            system_blocks.append({"type": "text", "text": system_volatile})

        user_content = (
            f"{instruction}\n\n"
            "Dati (gia' calcolati, da non ricalcolare):\n"
            "```json\n"
            f"{json.dumps(user_payload, ensure_ascii=False, indent=2, default=str)}\n"
            "```"
        )

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": json_schema},
            },
        }

        response = self._call(request)

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefused(f"richiesta declinata dai classificatori (categoria: {category})")

        self._accumulate_usage(response)

        text = next(
            (block.text for block in response.content
             if getattr(block, "type", None) == "text"),
            None,
        )
        if not text:
            raise RuntimeError("risposta priva di blocco testuale")

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"output non conforme allo schema JSON: {exc}") from exc

    # ── invio con fallback progressivo ───────────────────────────────────────

    def _call(self, request: dict[str, Any]):
        """Prova prima la variante piu' ricca, poi degrada.

        Le versioni dell'SDK e i permessi dell'organizzazione variano: invece
        di far fallire l'intero report perche' una beta non e' disponibile,
        si rimuove la funzionalita' opzionale e si riprova. La risposta
        peggiora leggermente; il report esce comunque.
        """
        attempts = [
            ("beta+fallback", lambda: self.client.beta.messages.create(
                betas=[_FALLBACK_BETA], fallbacks="default", **request)),
            ("standard", lambda: self.client.messages.create(**request)),
            ("senza_effort", lambda: self.client.messages.create(
                **{**request, "output_config": {
                    "format": request["output_config"]["format"]}})),
        ]

        last_error: Optional[Exception] = None
        for label, attempt in attempts:
            try:
                return attempt()
            except self._anthropic.APIStatusError as exc:
                # 4xx diversi da rate limit: quasi sempre un parametro non
                # supportato. Vale la pena degradare e riprovare.
                if exc.status_code in (400, 404):
                    logger.warning("tentativo LLM '%s' respinto (%s), degrado",
                                   label, exc.status_code)
                    last_error = exc
                    continue
                raise
            except TypeError as exc:
                logger.warning("tentativo LLM '%s' non supportato dall'SDK: %s", label, exc)
                last_error = exc
                continue

        raise RuntimeError(f"nessuna variante di chiamata accettata: {last_error}")

    def _accumulate_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        for field in self.usage:
            self.usage[field] += getattr(usage, field, 0) or 0

    # ── costo indicativo ─────────────────────────────────────────────────────

    def cost_estimate_usd(self) -> Optional[float]:
        """Costo indicativo della sessione, se il modello e' a listino noto.

        Ritorna None per un modello non in tabella invece di inventare un
        prezzo: un costo sbagliato e' peggio di nessun costo.
        """
        rates = {                       # (input, output) USD per milione di token
            "claude-opus-5": (5.0, 25.0),
            "claude-opus-4-8": (5.0, 25.0),
            "claude-sonnet-5": (3.0, 15.0),
            "claude-haiku-4-5": (1.0, 5.0),
        }
        rate = rates.get(self.model)
        if rate is None:
            return None
        billable_in = self.usage["input_tokens"] + self.usage["cache_creation_input_tokens"] * 1.25
        cached = self.usage["cache_read_input_tokens"] * 0.10
        cost = ((billable_in + cached) * rate[0] + self.usage["output_tokens"] * rate[1]) / 1e6
        return round(cost, 5)


def try_build(**kwargs) -> Optional[ClaudeClient]:
    """Costruisce il client se possibile, altrimenti None (nessuna eccezione)."""
    try:
        return ClaudeClient(**kwargs)
    except LLMUnavailable as exc:
        logger.info("agente 5 in modalita' template: %s", exc)
        return None
