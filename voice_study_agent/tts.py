"""Synthesize spoken text into audio using a cloud premium voice.

Two providers are supported behind one interface:

* **OpenAI** (``tts-1`` / ``tts-1-hd``) — default. Has a ~4096 character limit
  per request, so long text is split at sentence boundaries and the resulting
  MP3 chunks are concatenated (MP3 frames concatenate cleanly for playback).
* **ElevenLabs** (``eleven_multilingual_v2``) — very natural Italian voices.

Both return raw MP3 ``bytes`` that Streamlit can play with ``st.audio`` and the
user can download. The SDKs are imported lazily so the module loads without them
installed, failing only when a provider is actually invoked.
"""
from __future__ import annotations

import re
from typing import Callable

from . import config

ProgressFn = Callable[[int, int], None]  # (done_chars_or_chunks, total)


class TTSError(RuntimeError):
    """Raised when speech synthesis cannot run or the provider errors out."""


# ── Chunking ──────────────────────────────────────────────────────────────────
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def chunk_text(text: str, max_chars: int = 3800) -> list[str]:
    """Split text into chunks under ``max_chars``, preferring sentence breaks.

    A single sentence longer than the limit is hard-split on whitespace so no
    chunk ever exceeds the provider's cap.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            words = sentence.split(" ")
            piece = ""
            for word in words:
                # A single token longer than the cap (rare) is sliced hard.
                while len(word) > max_chars:
                    if piece:
                        chunks.append(piece.strip())
                        piece = ""
                    chunks.append(word[:max_chars])
                    word = word[max_chars:]
                if len(piece) + len(word) + 1 > max_chars:
                    chunks.append(piece.strip())
                    piece = word
                else:
                    piece = f"{piece} {word}".strip()
            if piece:
                current = piece
            continue
        if len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


# ── OpenAI ────────────────────────────────────────────────────────────────────
def _synthesize_openai(
    text: str, *, voice: str, model: str, api_key: str, progress: ProgressFn | None
) -> bytes:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise TTSError("Serve l'SDK 'openai'. Installa con: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    chunks = chunk_text(text, max_chars=3800)
    audio = bytearray()
    for i, chunk in enumerate(chunks, start=1):
        try:
            response = client.audio.speech.create(
                model=model, voice=voice, input=chunk, response_format="mp3"
            )
            audio.extend(response.read())
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Errore TTS OpenAI (blocco {i}/{len(chunks)}): {exc}") from exc
        if progress:
            progress(i, len(chunks))
    return bytes(audio)


# ── ElevenLabs ────────────────────────────────────────────────────────────────
def _synthesize_elevenlabs(
    text: str,
    *,
    voice_id: str,
    model: str,
    api_key: str,
    progress: ProgressFn | None,
) -> bytes:
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise TTSError(
            "Serve l'SDK 'elevenlabs'. Installa con: pip install elevenlabs"
        ) from exc

    client = ElevenLabs(api_key=api_key)
    chunks = chunk_text(text, max_chars=4800)
    audio = bytearray()
    for i, chunk in enumerate(chunks, start=1):
        try:
            stream = client.text_to_speech.convert(
                voice_id=voice_id,
                model_id=model,
                text=chunk,
                output_format="mp3_44100_128",
            )
            for part in stream:
                audio.extend(part)
        except Exception as exc:  # noqa: BLE001
            raise TTSError(
                f"Errore TTS ElevenLabs (blocco {i}/{len(chunks)}): {exc}"
            ) from exc
        if progress:
            progress(i, len(chunks))
    return bytes(audio)


# ── Public entry point ────────────────────────────────────────────────────────
def synthesize(
    text: str,
    *,
    provider: str | None = None,
    voice: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    progress: ProgressFn | None = None,
) -> bytes:
    """Synthesize ``text`` to MP3 bytes with the selected cloud provider.

    Falls back to sensible defaults from :mod:`config` for anything omitted.
    Raises :class:`TTSError` on any misconfiguration or provider failure.
    """
    if not text or not text.strip():
        raise TTSError("Nessun testo da sintetizzare.")

    provider = (provider or config.get_tts_provider()).lower()

    if provider == "openai":
        key = api_key or config.get_openai_api_key()
        if not key:
            raise TTSError(
                "Manca OPENAI_API_KEY nel file .env per la voce cloud OpenAI."
            )
        return _synthesize_openai(
            text,
            voice=voice or config.get_openai_tts_voice(),
            model=model or config.get_openai_tts_model(),
            api_key=key,
            progress=progress,
        )

    if provider == "elevenlabs":
        key = api_key or config.get_elevenlabs_api_key()
        if not key:
            raise TTSError(
                "Manca ELEVENLABS_API_KEY nel file .env per la voce cloud ElevenLabs."
            )
        return _synthesize_elevenlabs(
            text,
            voice_id=voice or config.get_elevenlabs_voice_id(),
            model=model or config.get_elevenlabs_model(),
            api_key=key,
            progress=progress,
        )

    if provider == "browser":
        raise TTSError(
            "Il provider 'browser' non genera un file audio: usa il player "
            "integrato nell'app (Web Speech API)."
        )

    raise TTSError(f"Provider TTS sconosciuto: '{provider}'.")
