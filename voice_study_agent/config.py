"""Centralised configuration for the voice study agent.

Reads the same ``.env`` used by the rest of the project (so the existing
``ANTHROPIC_API_KEY`` is reused for the LLM reordering step) and adds a small
set of TTS-specific variables for the cloud voice providers.

Nothing here performs network calls; the getters only read environment
variables so the Streamlit app can show what is configured before any request
is made.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


# ── LLM (text reordering with Claude) ─────────────────────────────────────────
def get_anthropic_api_key() -> str | None:
    """Cloud Claude key, shared with the multi-agent pipeline's ``.env``."""
    return os.getenv("ANTHROPIC_API_KEY") or None


def get_anthropic_model() -> str:
    """Claude model used to rewrite raw slide text into a spoken explanation."""
    return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


# ── TTS (cloud premium voice) ─────────────────────────────────────────────────
def get_tts_provider() -> str:
    """Default speech backend: 'openai' | 'elevenlabs' | 'browser'.

    'browser' is the no-key fallback that speaks through the viewer's own
    Web Speech API; the two cloud options produce a downloadable MP3.
    """
    return (os.getenv("TTS_PROVIDER") or "openai").strip().lower()


def get_openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or None


def get_openai_tts_model() -> str:
    """'tts-1' (fast, cheaper) or 'tts-1-hd' (higher fidelity)."""
    return os.getenv("OPENAI_TTS_MODEL", "tts-1")


def get_openai_tts_voice() -> str:
    """One of: alloy, echo, fable, onyx, nova, shimmer. 'nova' reads Italian
    clearly, so it is the default here."""
    return os.getenv("OPENAI_TTS_VOICE", "nova")


def get_elevenlabs_api_key() -> str | None:
    return os.getenv("ELEVENLABS_API_KEY") or None


def get_elevenlabs_voice_id() -> str:
    """Rachel is a solid multilingual default; override per your account."""
    return os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


def get_elevenlabs_model() -> str:
    """'eleven_multilingual_v2' handles Italian well."""
    return os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")


# ── Study defaults ────────────────────────────────────────────────────────────
def get_default_language() -> str:
    return os.getenv("STUDY_LANGUAGE", "it")


DEFAULT_LANGUAGE = get_default_language()

# Sample documents already in the repo, offered as one-click choices in the UI.
SAMPLE_DOCUMENTS = {
    "Oral_presentation.pdf": PROJECT_ROOT / "Oral_presentation.pdf",
    "docs/Reply_projects.pdf": PROJECT_ROOT / "docs" / "Reply_projects.pdf",
}
