"""Streamlit UI for the voice study agent.

Run from the project root with:

    streamlit run voice_study_agent/app.py

Flow: pick a document (upload or a repo sample) → extract ordered sections →
rewrite them into spoken prose with Claude → generate a premium cloud voice
(OpenAI / ElevenLabs) you can listen to and download. A free browser-voice
player is offered as a no-key fallback.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# Allow `streamlit run voice_study_agent/app.py` (script mode) to import the
# package by absolute name.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from voice_study_agent import config, extract, narrate, tts  # noqa: E402
from voice_study_agent.narrate import NarrationError  # noqa: E402
from voice_study_agent.tts import TTSError  # noqa: E402

st.set_page_config(page_title="Agente vocale di studio", page_icon="🎧", layout="wide")

OPENAI_VOICES = ["nova", "shimmer", "alloy", "echo", "fable", "onyx"]
LANGUAGES = {"Italiano": "it", "English": "en", "Español": "es", "Français": "fr", "Deutsch": "de"}


# ── Session state helpers ─────────────────────────────────────────────────────
def _init_state() -> None:
    defaults = {
        "sections": [],
        "narrated": [],
        "doc_title": "",
        "audio_full": None,
        "audio_sections": {},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_document(title: str, sections: list) -> None:
    st.session_state.sections = sections
    st.session_state.doc_title = title
    st.session_state.narrated = []
    st.session_state.audio_full = None
    st.session_state.audio_sections = {}


def _render_browser_player(text: str, lang: str) -> None:
    """Embed a Web Speech API player that reads ``text`` in the browser."""
    # Escape '</' so a literal '</script>' in the text can't close the inline
    # script tag early ('<\/' is an equivalent JS string escape).
    payload = json.dumps(text).replace("</", "<\\/")
    lang_code = {"it": "it-IT", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}.get(
        lang, "it-IT"
    )
    html = f"""
    <div style="font-family:sans-serif;padding:8px;border:1px solid #ddd;border-radius:8px;">
      <button onclick="vsaPlay()" style="padding:6px 14px;margin-right:6px;">▶️ Leggi</button>
      <button onclick="vsaPause()" style="padding:6px 14px;margin-right:6px;">⏸ Pausa</button>
      <button onclick="vsaStop()" style="padding:6px 14px;margin-right:6px;">⏹ Stop</button>
      <label style="margin-left:10px;">Velocità
        <input id="vsaRate" type="range" min="0.6" max="1.6" step="0.1" value="1.0"
               onchange="vsaSetRate(this.value)">
      </label>
      <script>
        const vsaText = {payload};
        let vsaUtter = null;
        function vsaPlay() {{
          const synth = window.speechSynthesis;
          if (synth.paused && vsaUtter) {{ synth.resume(); return; }}
          synth.cancel();
          vsaUtter = new SpeechSynthesisUtterance(vsaText);
          vsaUtter.lang = "{lang_code}";
          vsaUtter.rate = parseFloat(document.getElementById('vsaRate').value);
          const v = synth.getVoices().find(x => x.lang && x.lang.startsWith("{lang_code}".slice(0,2)));
          if (v) vsaUtter.voice = v;
          synth.speak(vsaUtter);
        }}
        function vsaPause() {{ window.speechSynthesis.pause(); }}
        function vsaStop() {{ window.speechSynthesis.cancel(); }}
        function vsaSetRate(r) {{
          if (vsaUtter) {{ vsaUtter.rate = parseFloat(r); }}
        }}
      </script>
    </div>
    """
    st.components.v1.html(html, height=90)


_init_state()

# ── Sidebar: configuration ────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurazione")

    language_label = st.selectbox("Lingua della narrazione", list(LANGUAGES.keys()), index=0)
    language = LANGUAGES[language_label]

    st.subheader("Riordino testo (Claude)")
    anthropic_model = st.text_input("Modello Claude", value=config.get_anthropic_model())
    if config.get_anthropic_api_key():
        st.success("ANTHROPIC_API_KEY trovata")
    else:
        st.error("ANTHROPIC_API_KEY mancante nel file .env")

    st.subheader("Voce (TTS)")
    provider = st.radio(
        "Provider",
        ["openai", "elevenlabs", "browser"],
        format_func={
            "openai": "OpenAI (cloud premium)",
            "elevenlabs": "ElevenLabs (cloud premium)",
            "browser": "Voce del browser (gratis)",
        }.get,
        index=["openai", "elevenlabs", "browser"].index(config.get_tts_provider())
        if config.get_tts_provider() in ("openai", "elevenlabs", "browser")
        else 0,
    )

    voice: str | None = None
    tts_model: str | None = None
    if provider == "openai":
        voice = st.selectbox("Voce OpenAI", OPENAI_VOICES, index=0)
        tts_model = st.selectbox("Qualità", ["tts-1", "tts-1-hd"], index=0)
        if config.get_openai_api_key():
            st.success("OPENAI_API_KEY trovata")
        else:
            st.warning("OPENAI_API_KEY mancante nel file .env")
    elif provider == "elevenlabs":
        voice = st.text_input("Voice ID ElevenLabs", value=config.get_elevenlabs_voice_id())
        tts_model = config.get_elevenlabs_model()
        if config.get_elevenlabs_api_key():
            st.success("ELEVENLABS_API_KEY trovata")
        else:
            st.warning("ELEVENLABS_API_KEY mancante nel file .env")
    else:
        st.info("La voce del browser legge senza costi né API key, ma non produce un file scaricabile.")

    st.caption("Le chiavi si impostano nel file .env alla radice del progetto.")


# ── Main: document input ──────────────────────────────────────────────────────
st.title("🎧 Agente vocale di studio")
st.write(
    "Carica slide, PDF o appunti: l'agente li **riordina in modo logico con Claude** "
    "e te li **legge ad alta voce** con una voce naturale."
)

col_up, col_sample = st.columns([2, 1])
with col_up:
    uploaded = st.file_uploader(
        "Carica un documento",
        type=[e.lstrip(".") for e in extract.SUPPORTED_EXTENSIONS],
        help="Formati: PDF, PowerPoint (.pptx), Word (.docx), testo (.txt/.md)",
    )
with col_sample:
    sample_names = ["—"] + list(config.SAMPLE_DOCUMENTS.keys())
    sample_choice = st.selectbox("…oppure un documento del progetto", sample_names)

if st.button("📖 Estrai e ordina il testo", type="primary"):
    try:
        if uploaded is not None:
            data = uploaded.getvalue()
            name = uploaded.name
        elif sample_choice != "—":
            path = config.SAMPLE_DOCUMENTS[sample_choice]
            data = Path(path).read_bytes()
            name = sample_choice
        else:
            st.warning("Carica un file o scegli un documento del progetto.")
            st.stop()

        with st.spinner("Estrazione del testo in corso…"):
            sections = extract.extract_sections(data, name)
        if not sections:
            st.error("Nessun testo estraibile da questo documento.")
        else:
            _reset_document(Path(name).stem, sections)
            st.success(f"Estratte {len(sections)} sezioni da «{name}».")
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))

sections = st.session_state.sections

# ── Extracted sections preview ────────────────────────────────────────────────
if sections:
    st.divider()
    st.subheader(f"📄 Testo estratto — {len(sections)} sezioni")
    with st.expander("Anteprima del testo grezzo estratto", expanded=False):
        for s in sections:
            st.markdown(f"**{s.index}. {s.title}**")
            st.text(s.text[:1500] + ("…" if len(s.text) > 1500 else ""))
            if s.notes:
                st.caption(f"Note relatore: {s.notes[:400]}")

    # ── Narrate with Claude ───────────────────────────────────────────────────
    if st.button("🧠 Riordina e riscrivi con Claude"):
        if not config.get_anthropic_api_key():
            st.error("Manca ANTHROPIC_API_KEY nel file .env: impossibile riordinare con Claude.")
        else:
            progress_bar = st.progress(0.0, text="Preparazione…")

            def _on_progress(done: int, total: int, title: str) -> None:
                frac = done / total if total else 1.0
                progress_bar.progress(min(frac, 1.0), text=f"Sezione {done}/{total}: {title}")

            try:
                narrated = narrate.build_study_script(
                    sections,
                    doc_title=st.session_state.doc_title,
                    language=language,
                    model=anthropic_model,
                    progress=_on_progress,
                )
                st.session_state.narrated = narrated
                st.session_state.audio_full = None
                st.session_state.audio_sections = {}
                progress_bar.empty()
                st.success("Testo riscritto in forma parlata e ordinata.")
            except NarrationError as exc:
                progress_bar.empty()
                st.error(str(exc))

narrated = st.session_state.narrated

# ── Narrated script + audio ───────────────────────────────────────────────────
if narrated:
    st.divider()
    st.subheader("🗣️ Script parlato pronto all'ascolto")

    full_text = narrate.full_script_text(narrated)
    st.caption(f"{len(full_text):,} caratteri · {len(narrated)} sezioni")

    # Full-document premium audio.
    if provider in ("openai", "elevenlabs"):
        if st.button("🔊 Genera audio dell'intero documento", type="primary"):
            audio_bar = st.progress(0.0, text="Sintesi vocale…")

            def _tts_progress(done: int, total: int) -> None:
                audio_bar.progress(done / total if total else 1.0, text=f"Blocco {done}/{total}")

            try:
                audio = tts.synthesize(
                    full_text,
                    provider=provider,
                    voice=voice,
                    model=tts_model,
                    progress=_tts_progress,
                )
                st.session_state.audio_full = audio
                audio_bar.empty()
            except TTSError as exc:
                audio_bar.empty()
                st.error(str(exc))

        if st.session_state.audio_full:
            st.audio(st.session_state.audio_full, format="audio/mp3")
            st.download_button(
                "⬇️ Scarica MP3",
                data=st.session_state.audio_full,
                file_name=f"{st.session_state.doc_title or 'studio'}.mp3",
                mime="audio/mpeg",
            )
    else:
        # Browser Web Speech API player (no key, no file).
        _render_browser_player(full_text, language)

    st.divider()
    st.subheader("📑 Sezioni")
    for n in narrated:
        with st.expander(f"{n.index}. {n.title}", expanded=False):
            edited = st.text_area(
                "Testo parlato (modificabile)",
                value=n.spoken_text,
                key=f"txt_{n.index}",
                height=180,
            )
            n.spoken_text = edited  # keep edits in the in-memory objects

            if provider in ("openai", "elevenlabs"):
                if st.button("🔊 Genera audio di questa sezione", key=f"gen_{n.index}"):
                    try:
                        with st.spinner("Sintesi vocale…"):
                            st.session_state.audio_sections[n.index] = tts.synthesize(
                                edited, provider=provider, voice=voice, model=tts_model
                            )
                    except TTSError as exc:
                        st.error(str(exc))
                if n.index in st.session_state.audio_sections:
                    st.audio(st.session_state.audio_sections[n.index], format="audio/mp3")
