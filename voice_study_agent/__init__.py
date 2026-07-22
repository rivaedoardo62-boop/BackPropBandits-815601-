"""Voice study agent: read study documents aloud, logically reordered.

Pipeline
--------
1. :mod:`extract`  — document (PDF/PPTX/DOCX/TXT) → ordered ``Section`` list.
2. :mod:`narrate`  — each section rewritten by Claude into spoken prose.
3. :mod:`tts`      — spoken text → MP3 audio via a cloud premium voice.

The Streamlit UI in :mod:`app` wires these together.
"""
from __future__ import annotations

from . import config, extract, narrate, tts

__all__ = ["config", "extract", "narrate", "tts"]
__version__ = "0.1.0"
