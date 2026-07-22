# 🎧 Agente vocale di studio

Uno strumento che prende un documento di studio (slide, PDF, appunti), **lo
riordina in modo logico con Claude** e te lo **legge ad alta voce** con una voce
naturale. Pensato come supporto allo studio: trasforma gli elenchi puntati delle
slide in una spiegazione discorsiva e ordinata, facile da ascoltare.

È un modulo indipendente dal resto del progetto *Airport Risk Intelligence*:
vive tutto dentro `voice_study_agent/` e non tocca l'app Streamlit dell'analisi.

---

## Come funziona (pipeline)

```
Documento ──▶ estrazione ──▶ riordino con Claude ──▶ sintesi vocale ──▶ 🔊 audio
 PDF/PPTX/     (extract.py)     (narrate.py)            (tts.py)          MP3 +
 DOCX/TXT      sezioni in       spiegazione parlata,    voce cloud        download
               ordine           ordinata, fedele        premium
```

1. **`extract.py`** — estrae il testo in sezioni ordinate (una per pagina PDF /
   slide PowerPoint / titolo Word), pulendo intestazioni e numeri di pagina.
2. **`narrate.py`** — ogni sezione viene riscritta da Claude in prosa parlata:
   gli elenchi diventano frasi complete e collegate, i termini tecnici vengono
   spiegati, l'ordine è quello più logico per capire. Resta **fedele** al
   contenuto, non inventa nulla.
3. **`tts.py`** — il testo parlato diventa audio MP3 con una voce cloud premium
   (**OpenAI** di default, oppure **ElevenLabs**). Il testo lungo viene spezzato
   automaticamente ai limiti dei provider.
4. **`app.py`** — l'interfaccia Streamlit che collega tutto.

---

## Installazione

Dalla radice del progetto:

```bash
pip install -r voice_study_agent/requirements.txt
```

## Configurazione delle chiavi

Copia `.env.example` in `.env` (se non l'hai già fatto) e compila:

```dotenv
# Riordino testo con Claude (già usato dal resto del progetto)
ANTHROPIC_API_KEY=la-tua-chiave
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# Voce cloud premium
TTS_PROVIDER=openai            # openai | elevenlabs | browser
OPENAI_API_KEY=la-tua-chiave
OPENAI_TTS_VOICE=nova          # alloy | echo | fable | onyx | nova | shimmer
OPENAI_TTS_MODEL=tts-1         # tts-1 (veloce) | tts-1-hd (qualità)

STUDY_LANGUAGE=it
```

> Non serve una API key TTS per provare subito: imposta `TTS_PROVIDER=browser`
> (o scegli "Voce del browser" nell'app) e la lettura avviene con le voci del
> browser, senza costi. La voce cloud serve solo per l'audio scaricabile (MP3).

## Avvio

```bash
streamlit run voice_study_agent/app.py
```

Poi nel browser:

1. Carica un documento (o scegli una delle slide del progetto già pronte).
2. **📖 Estrai e ordina il testo** → vedi l'anteprima delle sezioni.
3. **🧠 Riordina e riscrivi con Claude** → ottieni lo script parlato.
4. **🔊 Genera audio** (intero documento o singola sezione) → ascolta e scarica.

Puoi modificare a mano il testo di ogni sezione prima di generare l'audio.

---

## Formati supportati

| Formato | Estensione | Unità di sezione |
|---|---|---|
| PDF | `.pdf` | una pagina |
| PowerPoint | `.pptx` | una slide (note del relatore incluse) |
| Word | `.docx` | uno stile "Titolo/Heading" |
| Testo / Markdown | `.txt`, `.md` | un'intestazione `#` |

## Lingue

Italiano (default), inglese, spagnolo, francese, tedesco — selezionabili nella
barra laterale.

## Costi

- **Claude** riscrive una volta per sezione: costo proporzionale alla lunghezza
  del documento.
- **TTS cloud** si paga a carattere sintetizzato; genera l'audio solo quando ti
  serve. La modalità **browser** è gratuita.

## Struttura del modulo

```
voice_study_agent/
├── app.py            # interfaccia Streamlit
├── extract.py        # estrazione testo (PDF/PPTX/DOCX/TXT)
├── narrate.py        # riordino/riscrittura con Claude
├── tts.py            # sintesi vocale (OpenAI / ElevenLabs) + chunking
├── config.py         # lettura .env e default
├── requirements.txt  # dipendenze aggiuntive
└── README.md
```
