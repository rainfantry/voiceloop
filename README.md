# VoiceLoop

Local 2-way voice conversation with any Ollama model. No cloud. No API keys. No billing. Runs entirely on your machine.

You talk → Whisper transcribes → Ollama thinks → SAPI speaks back. Loop.

Optional: load a folder of markdown files as RAG context so the model can reference your notes, research, or documentation during the conversation.

## Build Journal

### The Problem

I was looking at ElevenLabs' conversational AI agents — they let you build a custom agent that ingests RAG files, does text-to-speech, listens to your voice with speech-to-text, and has a full 2-way call conversation mode. It's slick. It's also cloud-dependent, rate-limited, and costs money per minute.

I wanted to know: can I build this locally? My hardware isn't special — a Windows laptop with a webcam mic. No GPU. The question was whether the STT piece could run fast enough on CPU to feel conversational.

### The Stack I Chose

**Speech-to-Text: faster-whisper**

OpenAI's Whisper is the obvious choice for offline STT. But the original `whisper` Python package is slow as shit on CPU. `faster-whisper` is a CTranslate2 port that runs 4x faster with int8 quantisation. The `base` model transcribes a sentence in ~1-2 seconds on CPU. Good enough.

I considered `vosk` (lighter, faster) but Whisper's accuracy is noticeably better, especially with technical vocabulary. Since I'm using this to study cybersecurity concepts, accuracy matters more than shaving 500ms.

Install:
```
pip install faster-whisper
```

The first run downloads the model (~150MB for `base`). It caches in `~/.cache/huggingface/`.

**LLM: Ollama**

I already had Ollama running locally with several models. VoiceLoop connects to it via the `/api/chat` endpoint. Any model works — swap with `--model`.

The critical discovery: my Ollama was configured to bind to my LAN IP (`192.168.1.92:11434`) instead of localhost, via the `OLLAMA_HOST` environment variable. VoiceLoop reads this env var automatically so it just works regardless of your config.

If you don't have Ollama:
```
# Install from https://ollama.com
# Then pull a model:
ollama pull llama3.2:3b     # small, fast
ollama pull qwen2.5:7b      # bigger, smarter
```

**Text-to-Speech: Windows SAPI via pyttsx3**

No contest here. `pyttsx3` wraps Windows SAPI5 which is built into every Windows install. Zero setup, zero latency, zero cost. The voice quality isn't neural-TTS-tier but it's instant and reliable.

On Linux it falls back to `espeak-ng`. Same API.

Install:
```
pip install pyttsx3
```

On Linux you also need:
```
sudo apt install espeak-ng
```

**Audio Capture: sounddevice**

I tried PyAudio first but it doesn't have wheels for Python 3.14. `sounddevice` installed clean and handles the mic input. It captures raw float32 PCM at 16kHz which is exactly what Whisper wants.

```
pip install sounddevice numpy
```

### How the Conversation Loop Works

```
┌──────────────────────────────────────────┐
│  1. Mic listens (sounddevice callback)   │
│     ↓ voice activity detected            │
│  2. Record until 1.5s silence            │
│     ↓ raw audio buffer                   │
│  3. Whisper transcribes (CPU, ~1-2s)     │
│     ↓ text                               │
│  4. Ollama generates (streaming)         │
│     ↓ tokens stream in                   │
│  5. SAPI speaks sentence-by-sentence     │
│     as tokens arrive (not waiting for    │
│     full response)                       │
│  6. Loop back to 1                       │
└──────────────────────────────────────────┘
```

The streaming TTS is important. Without it, you'd wait for the full Ollama response (could be 5-10 seconds on a 7B model) and THEN wait for TTS to read it all. With streaming, SAPI starts reading the first sentence while Ollama is still generating the rest. Feels way more conversational.

Voice activity detection is simple: RMS amplitude threshold on the mic input. When the signal crosses the threshold, recording starts. When silence persists for 1.5 seconds, recording stops. No fancy VAD model needed.

### How RAG Works

The `--rag` flag points to a folder of `.md` files. At startup, VoiceLoop loads every markdown file, indexes it by keyword, and stores the chunks in memory.

When you ask a question, your words are tokenised into keywords, matched against each chunk's keyword set (extracted from the title and first 2000 chars), and the top match gets injected into the system prompt as reference material.

It's not vector embeddings or semantic search — it's keyword overlap scoring. For a focused knowledge base (like my 14-chapter cybersecurity research), this works surprisingly well. "What are oplocks?" pulls Chapter 6. "Explain TOCTOU" pulls Chapter 9. The keywords do the routing.

The context is capped at ~4000 chars per query to stay within the model's context window. A 7B model with 8K context can handle the system prompt + RAG chunk + conversation history comfortably.

**Why not embeddings?** Because it would add a dependency (sentence-transformers, ~2GB model download), require a vector DB or at minimum numpy similarity search, and for 14 files it's overkill. Keyword matching is instant and good enough.

### Tuning for Conversation Mode

The biggest lesson: **a voice assistant is NOT a chatbot.** The model's instinct is to dump paragraphs with markdown headers, bullet points, and code blocks. None of that works when it's being read aloud by SAPI.

Fixes:
1. **System prompt enforces brevity** — "2-3 sentences MAX. No markdown. Plain spoken English only."
2. **`num_predict` cap** — hard limit on response tokens (default 150). The model physically can't write an essay.
3. **Markdown stripping** — the TTS pipeline strips `#*_[]()>|` characters before speaking, so if the model slips markdown through, it doesn't read "hashtag hashtag heading".
4. **Temperature 0.7** — slightly creative but not rambling.
5. **Short conversation history** — only the last 8 messages go into context. Keeps it snappy and prevents context window overflow.

### Latency Breakdown

On my hardware (no GPU, i7 laptop, webcam mic):

| Stage | Time |
|-------|------|
| Record + silence detection | ~2-3s (depends on how long you talk) |
| Whisper transcription (base, CPU) | ~1-2s |
| Ollama first token (7B model) | ~1-2s |
| SAPI first sentence spoken | ~0.5s after first sentence generated |
| **Total to first speech** | **~4-6s** |

Not instant. But conversational enough — about the same latency as talking to someone on a bad phone connection. Using `--whisper tiny` and a smaller model (3B) cuts it to ~3s.

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed with at least one model pulled
- A microphone (webcam mic, headset, USB mic — anything)
- Windows (SAPI TTS) or Linux (espeak-ng)

### Install

```bash
git clone https://github.com/rainfantry/voiceloop.git
cd voiceloop

# Windows
setup.bat

# Linux/macOS
chmod +x setup.sh && ./setup.sh

# Or manual
pip install -r requirements.txt
```

### Run

```bash
# Basic conversation
python voiceloop.py

# With a specific model
python voiceloop.py --model llama3.2:3b

# With RAG context (folder of .md files)
python voiceloop.py --rag /path/to/your/notes

# All options
python voiceloop.py --model qwen2.5:7b --rag ./docs --whisper small --threshold 300 --max-tokens 200
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `coding:latest` | Ollama model name |
| `--rag` | none | Folder of `.md` files for RAG context |
| `--whisper` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium` |
| `--threshold` | `500` | Mic silence threshold (lower = more sensitive) |
| `--max-tokens` | `150` | Max response length in tokens |

### Troubleshooting

**"Ollama didn't respond"**
- Is Ollama running? `ollama serve` or check the tray icon
- Check your `OLLAMA_HOST` env var — VoiceLoop reads it automatically
- Test: `curl http://localhost:11434/` (or your OLLAMA_HOST)

**Mic not picking up / triggers on noise**
- `--threshold 300` for quiet environments, `--threshold 800` for noisy ones
- Check your default input device in Windows Sound Settings

**Responses too long / too short**
- `--max-tokens 100` for snappier responses
- `--max-tokens 300` if you want more detail

**Whisper accuracy is bad**
- `--whisper small` is significantly better than `base` (but slower)
- Make sure you're speaking English (hardcoded `language="en"`)

## Architecture

```
voiceloop.py          — single-file, ~280 lines, no external services
├── STT layer         — faster-whisper, CPU int8, configurable model size
├── VAD               — RMS amplitude threshold (no ML model needed)
├── LLM               — Ollama REST API, streaming, conversation history
├── RAG               — keyword-match retrieval from .md files
├── TTS               — pyttsx3/SAPI5, sentence-by-sentence streaming
└── Threading         — TTS runs on separate thread, speaks as tokens arrive
```

## License

Do whatever you want with it. No license. No attribution required.
