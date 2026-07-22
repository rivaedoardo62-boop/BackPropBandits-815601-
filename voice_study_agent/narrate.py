"""Rewrite raw document sections into a clear, spoken study narration.

The extractor gives us slide/page text as it appears on the page: bullet
fragments, tables read left-to-right, half sentences. This module asks Claude to
turn each section into flowing, logically ordered prose meant to be *listened
to* — expanding bullets into full sentences, defining jargon, and keeping the
order that makes pedagogical sense — while staying faithful to the source and
never inventing facts.

Output is plain text with no Markdown or symbols, ready to hand to a TTS engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import config
from .extract import Section

# Type alias for an optional progress hook: (done, total, section_title) -> None
ProgressFn = Callable[[int, int, str], None]

_LANGUAGE_NAMES = {
    "it": "italiano",
    "en": "inglese",
    "es": "spagnolo",
    "fr": "francese",
    "de": "tedesco",
}

_SYSTEM_PROMPT = """Sei un tutor universitario esperto e un divulgatore chiaro.
Il tuo compito è trasformare il testo grezzo di una slide o pagina di studio in
una spiegazione discorsiva pensata per essere ASCOLTATA ad alta voce, non letta.

Regole ferree:
- Scrivi in {language}. Tono calmo, chiaro, da lezione, in seconda persona quando aiuta ("nota che...", "ricorda che...").
- Espandi gli elenchi puntati in frasi complete e collegate da nessi logici (perché, quindi, di conseguenza, in altre parole).
- Riordina i concetti nell'ordine più logico per capirli, anche se sulla slide erano sparsi.
- Spiega brevemente i termini tecnici e le sigle la prima volta che compaiono.
- RESTA FEDELE al contenuto: non aggiungere fatti, numeri o esempi che non ci sono. Se il testo è ambiguo o incompleto, spiega solo ciò che è presente senza inventare.
- NIENTE markdown, niente asterischi, niente titoli, niente simboli o emoji: solo testo scorrevole pronunciabile. Scrivi i numeri e le formule in parole quando è naturale.
- Non dire "questa slide" o "in questa pagina"; parla direttamente del contenuto.
- Sii conciso ma completo: meglio poche frasi dense e chiare che un riassunto vago.

Restituisci SOLO la spiegazione, senza premesse del tipo "Ecco la spiegazione"."""

_USER_TEMPLATE = """Documento: "{doc_title}" — sezione {index} di {total}.
Titolo della sezione: {section_title}

Testo grezzo estratto (può contenere frammenti, elenchi, tabelle disordinate):
---
{raw_text}
---
{notes_block}
Trasforma questo materiale in una spiegazione parlata, chiara e ordinata, in {language}."""


@dataclass
class NarratedSection:
    """A section after Claude has rewritten it for listening."""

    index: int
    title: str
    spoken_text: str
    source_kind: str = "section"


def _clean_llm_output(text: str) -> str:
    """Strip any stray Markdown the model may still emit so the TTS reads clean
    prose rather than pronouncing asterisks and hashes."""
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class NarrationError(RuntimeError):
    """Raised when the LLM reordering cannot run (missing key/SDK/API error)."""


def _make_client(api_key: str):
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise NarrationError(
            "Serve l'SDK 'anthropic'. Installa con: pip install anthropic"
        ) from exc
    return Anthropic(api_key=api_key)


def narrate_section(
    client,
    section: Section,
    *,
    doc_title: str,
    total: int,
    language: str,
    model: str,
    max_tokens: int = 1200,
) -> NarratedSection:
    """Rewrite a single section into spoken prose."""
    lang_name = _LANGUAGE_NAMES.get(language, language)
    notes_block = ""
    if section.notes.strip():
        notes_block = (
            "Note del relatore (usale per chiarire, non ripeterle testualmente):\n"
            f"{section.notes.strip()}\n"
        )

    user_msg = _USER_TEMPLATE.format(
        doc_title=doc_title,
        index=section.index,
        total=total,
        section_title=section.title,
        raw_text=section.text or "(nessun testo, usa eventuali note del relatore)",
        notes_block=notes_block,
        language=lang_name,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SYSTEM_PROMPT.format(language=lang_name),
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:  # noqa: BLE001 - surface any API error to the UI
        raise NarrationError(f"Errore chiamando Claude: {exc}") from exc

    parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    spoken = _clean_llm_output("".join(parts))
    return NarratedSection(
        index=section.index,
        title=section.title,
        spoken_text=spoken,
        source_kind=section.kind,
    )


def build_study_script(
    sections: list[Section],
    *,
    doc_title: str = "Documento di studio",
    language: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    progress: ProgressFn | None = None,
) -> list[NarratedSection]:
    """Rewrite every section into a spoken narration, in reading order.

    Raises :class:`NarrationError` if no Anthropic key is configured. Sections
    are processed sequentially to keep the pedagogical order predictable and the
    request rate gentle.
    """
    language = language or config.get_default_language()
    model = model or config.get_anthropic_model()
    api_key = api_key or config.get_anthropic_api_key()
    if not api_key:
        raise NarrationError(
            "Manca ANTHROPIC_API_KEY nel file .env: non posso riordinare il testo con Claude."
        )

    client = _make_client(api_key)
    total = len(sections)
    narrated: list[NarratedSection] = []
    for i, section in enumerate(sections, start=1):
        if progress:
            progress(i - 1, total, section.title)
        narrated.append(
            narrate_section(
                client,
                section,
                doc_title=doc_title,
                total=total,
                language=language,
                model=model,
            )
        )
    if progress:
        progress(total, total, "Completato")
    return narrated


def full_script_text(narrated: list[NarratedSection]) -> str:
    """Concatenate all sections into a single readable script."""
    return "\n\n".join(n.spoken_text for n in narrated if n.spoken_text.strip())
