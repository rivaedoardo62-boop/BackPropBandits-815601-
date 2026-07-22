"""Turn a study document into an ordered list of sections.

Supported inputs: PDF (one section per page), PowerPoint ``.pptx`` (one section
per slide, notes included), Word ``.docx`` (split on heading styles) and plain
``.txt`` / ``.md`` (split on Markdown headings).

The heavy parsers (``pypdf``, ``python-pptx``, ``python-docx``) are imported
lazily so the module loads even when a given format's dependency is missing; the
caller then gets a clear, actionable error only for the format actually used.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    """A logical unit of the document, in reading order."""

    index: int
    title: str
    text: str
    kind: str = "section"  # "page" | "slide" | "heading" | "section"
    notes: str = field(default="")

    @property
    def is_empty(self) -> bool:
        return not (self.text.strip() or self.notes.strip())


# ── Text cleaning ─────────────────────────────────────────────────────────────
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:/\s*\d+)?\s*$", re.IGNORECASE)


def _normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of spaces/tabs but keep line breaks (they carry slide layout).
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ blank lines down to a single blank line.
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _strip_repeated_headers(pages: list[str]) -> list[str]:
    """Remove lines that repeat as a header/footer on most pages (running
    titles, page numbers) so the narration is not littered with them."""
    if len(pages) < 3:
        return pages

    from collections import Counter

    first_lines: Counter[str] = Counter()
    last_lines: Counter[str] = Counter()
    for page in pages:
        lines = [ln for ln in page.split("\n") if ln.strip()]
        if lines:
            first_lines[lines[0]] += 1
            last_lines[lines[-1]] += 1

    threshold = max(3, int(len(pages) * 0.6))
    boilerplate = {ln for ln, c in first_lines.items() if c >= threshold}
    boilerplate |= {ln for ln, c in last_lines.items() if c >= threshold}

    cleaned = []
    for page in pages:
        kept = [
            ln
            for ln in page.split("\n")
            if ln not in boilerplate and not _PAGE_NUMBER_RE.match(ln)
        ]
        cleaned.append("\n".join(kept).strip())
    return cleaned


# ── Format-specific extractors ────────────────────────────────────────────────
def _extract_pdf(data: bytes) -> list[Section]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Per leggere i PDF serve 'pypdf'. Installa con: pip install pypdf"
        ) from exc

    reader = PdfReader(io.BytesIO(data))
    raw_pages = [_normalise_whitespace(page.extract_text() or "") for page in reader.pages]
    raw_pages = _strip_repeated_headers(raw_pages)

    sections: list[Section] = []
    for i, text in enumerate(raw_pages, start=1):
        first_line = next((ln for ln in text.split("\n") if ln.strip()), "")
        title = first_line[:80] if first_line else f"Pagina {i}"
        sections.append(Section(index=i, title=title, text=text, kind="page"))
    return sections


def _extract_pptx(data: bytes) -> list[Section]:
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Per leggere i PowerPoint serve 'python-pptx'. "
            "Installa con: pip install python-pptx"
        ) from exc

    prs = Presentation(io.BytesIO(data))
    sections: list[Section] = []
    for i, slide in enumerate(prs.slides, start=1):
        title = ""
        body_parts: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            shape_text = "\n".join(
                p.text for p in shape.text_frame.paragraphs if p.text.strip()
            )
            if not shape_text.strip():
                continue
            if not title and shape == slide.shapes.title:
                title = shape_text.strip().split("\n")[0]
            else:
                body_parts.append(shape_text)

        notes = ""
        if slide.has_notes_slide:
            notes = _normalise_whitespace(
                slide.notes_slide.notes_text_frame.text or ""
            )

        sections.append(
            Section(
                index=i,
                title=(title or f"Slide {i}")[:80],
                text=_normalise_whitespace("\n".join(body_parts)),
                kind="slide",
                notes=notes,
            )
        )
    return sections


def _extract_docx(data: bytes) -> list[Section]:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Per leggere i Word serve 'python-docx'. "
            "Installa con: pip install python-docx"
        ) from exc

    document = docx.Document(io.BytesIO(data))
    sections: list[Section] = []
    current_title = "Introduzione"
    current_body: list[str] = []
    index = 1

    def _flush() -> None:
        nonlocal index, current_body
        body = _normalise_whitespace("\n".join(current_body))
        if body or index == 1:
            sections.append(
                Section(index=index, title=current_title[:80], text=body, kind="heading")
            )
            index += 1
        current_body = []

    for para in document.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading") and para.text.strip():
            _flush()
            current_title = para.text.strip()
        elif para.text.strip():
            current_body.append(para.text.strip())
    _flush()
    return [s for s in sections if not s.is_empty] or [
        Section(index=1, title="Documento", text="", kind="heading")
    ]


def _extract_text(data: bytes) -> list[Section]:
    text = data.decode("utf-8", errors="replace")
    # Split on Markdown headings; keep everything before the first heading too.
    parts = re.split(r"(?m)^(#{1,6})\s+(.*)$", text)
    sections: list[Section] = []
    index = 1

    preamble = parts[0].strip()
    if preamble:
        sections.append(
            Section(index=index, title="Introduzione", text=_normalise_whitespace(preamble))
        )
        index += 1

    # After the split, groups come in triples: (hashes, title, body).
    for i in range(1, len(parts), 3):
        title = parts[i + 1].strip() if i + 1 < len(parts) else "Sezione"
        body = parts[i + 2] if i + 2 < len(parts) else ""
        sections.append(
            Section(index=index, title=title[:80], text=_normalise_whitespace(body))
        )
        index += 1

    if not sections:
        sections.append(Section(index=1, title="Documento", text=_normalise_whitespace(text)))
    return sections


# ── Public entry point ────────────────────────────────────────────────────────
_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".pptx": _extract_pptx,
    ".docx": _extract_docx,
    ".txt": _extract_text,
    ".md": _extract_text,
    ".markdown": _extract_text,
}

SUPPORTED_EXTENSIONS = tuple(_EXTRACTORS.keys())


def extract_sections(data: bytes, filename: str) -> list[Section]:
    """Extract ordered, cleaned sections from a document given its raw bytes.

    ``filename`` is only used for its extension (to pick the parser).
    """
    suffix = Path(filename).suffix.lower()
    extractor = _EXTRACTORS.get(suffix)
    if extractor is None:
        raise ValueError(
            f"Formato non supportato: '{suffix}'. "
            f"Formati validi: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    sections = extractor(data)
    return [s for s in sections if not s.is_empty]


def extract_from_path(path: str | Path) -> list[Section]:
    path = Path(path)
    return extract_sections(path.read_bytes(), path.name)
