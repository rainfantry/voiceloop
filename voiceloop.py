#!/usr/bin/env python3
"""
VoiceLoop — Local 2-way voice conversation with RAG
STT: faster-whisper (offline)
LLM: Ollama (local)
TTS: Windows SAPI via pyttsx3 (streams sentence-by-sentence)
RAG: loads .md files, keyword-matches relevant chunks per question
"""

import sys
import os
import re
import glob
import json
import time
import argparse
import numpy as np
import sounddevice as sd
import pyttsx3
import requests
from faster_whisper import WhisperModel

# --- Config ---
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost:11434")
OLLAMA_URL = f"http://{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = "coding:latest"
WHISPER_MODEL_SIZE = "base"
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.5
MAX_RECORD_SECONDS = 30
RAG_MAX_CHARS = 4000
RAG_NUM_CHUNKS = 1
MAX_TOKENS = 150

DEFAULT_SYSTEM = """You are a voice assistant in a live conversation. RULES:
- Answer in 2-3 sentences MAX. This is spoken aloud — not a document.
- No markdown. No headers. No bullet points. No code blocks. No URLs.
- Plain spoken English only. Talk like a human, not a textbook.
- Be direct. Swear if it fits. No filler."""

RAG_SYSTEM = """You are VADER — a cybersecurity tutor in a live voice conversation. RULES:
- Answer in 2-3 sentences MAX. This is spoken aloud — not a document.
- No markdown. No headers. No bullet points. No code blocks. No URLs.
- Plain spoken English only. Explain like you're talking to someone, not writing a manual.
- Use the reference material below to answer accurately, but SUMMARISE — don't recite it.
- If asked to go deeper, give one more layer of detail. Still short.
- Be direct. Swear if it fits. Teach like a sergeant."""

# --- Globals ---
tts_engine = None
conversation = []
rag_chunks = []


def init_tts():
    global tts_engine
    tts_engine = pyttsx3.init("sapi5")
    voices = tts_engine.getProperty("voices")
    for v in voices:
        if "david" in v.name.lower() or "mark" in v.name.lower():
            tts_engine.setProperty("voice", v.id)
            break
    tts_engine.setProperty("rate", 200)
    tts_engine.setProperty("volume", 1.0)


def speak(text):
    clean = re.sub(r'[#*_`~\[\]()>|]', '', text).strip()
    if not clean:
        return
    try:
        tts_engine.say(clean)
        tts_engine.runAndWait()
    except Exception as e:
        print(f"[tts error] {e}", flush=True)


def init_whisper():
    print("[voiceloop] Loading Whisper model...", flush=True)
    model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("[voiceloop] Whisper ready.", flush=True)
    return model


def load_rag_folder(folder_path):
    if not os.path.isdir(folder_path):
        print(f"[rag] Folder not found: {folder_path}", flush=True)
        return []

    md_files = sorted(glob.glob(os.path.join(folder_path, "*.md")))
    if not md_files:
        print(f"[rag] No .md files in {folder_path}", flush=True)
        return []

    chunks = []
    for f in md_files:
        name = os.path.basename(f)
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        title = name.replace(".md", "").replace("_", " ")
        keywords = set(re.findall(r'[a-z]{3,}', (title + " " + content[:2000]).lower()))
        chunks.append({
            "name": name,
            "title": title,
            "content": content,
            "keywords": keywords,
            "chars": len(content)
        })

    total = sum(c["chars"] for c in chunks)
    print(f"[rag] Loaded {len(chunks)} files ({total:,} chars)", flush=True)
    for c in chunks:
        print(f"  - {c['name']} ({c['chars']:,} chars)", flush=True)

    return chunks


def retrieve_context(question, num_chunks=RAG_NUM_CHUNKS, max_chars=RAG_MAX_CHARS):
    if not rag_chunks:
        return ""

    q_words = set(re.findall(r'[a-z]{3,}', question.lower()))
    scored = []
    for chunk in rag_chunks:
        overlap = len(q_words & chunk["keywords"])
        scored.append((overlap, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = []
    total_chars = 0

    for score, chunk in scored[:num_chunks]:
        if score == 0:
            break
        text = chunk["content"]
        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 500:
                text = text[:remaining] + "\n[...truncated]"
            else:
                break
        selected.append(f"## {chunk['title']}\n{text}")
        total_chars += len(text)

    if not selected:
        best = scored[0][1] if scored else rag_chunks[0]
        text = best["content"][:max_chars]
        selected.append(f"## {best['title']}\n{text}\n[...truncated]")

    return "\n\n".join(selected)


def record_until_silence():
    audio_chunks = []
    silence_samples = 0
    silence_limit = int(SILENCE_DURATION * SAMPLE_RATE)
    max_samples = MAX_RECORD_SECONDS * SAMPLE_RATE
    total_samples = 0
    started = False

    print("\n[listening]", flush=True)

    def callback(indata, frames, time_info, status):
        nonlocal silence_samples, total_samples, started
        chunk = indata[:, 0].copy()
        rms = np.sqrt(np.mean(chunk ** 2)) * 32768

        if rms > SILENCE_THRESHOLD:
            started = True
            silence_samples = 0
        elif started:
            silence_samples += len(chunk)

        if started:
            audio_chunks.append(chunk)
            total_samples += len(chunk)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                        dtype="float32", blocksize=1024, callback=callback):
        while True:
            time.sleep(0.05)
            if started and silence_samples >= silence_limit:
                break
            if total_samples >= max_samples:
                break

    if not audio_chunks:
        return None

    return np.concatenate(audio_chunks)


def transcribe(model, audio):
    segments, _ = model.transcribe(audio, beam_size=5, language="en",
                                    vad_filter=True)
    text = " ".join(seg.text for seg in segments).strip()
    return text


def query_ollama(user_text):
    conversation.append({"role": "user", "content": user_text})

    if rag_chunks:
        context = retrieve_context(user_text)
        system_content = RAG_SYSTEM + f"\n\n# REFERENCE\n{context}"
    else:
        system_content = DEFAULT_SYSTEM

    messages = [{"role": "system", "content": system_content}] + conversation[-8:]

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": 8192,
                "num_predict": MAX_TOKENS,
                "temperature": 0.7,
            }
        }, stream=True, timeout=120)

        full_response = []
        tag = "[vader] " if rag_chunks else "[ai] "
        sys.stdout.write(tag)

        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                full_response.append(token)
                sys.stdout.write(token)
                sys.stdout.flush()
                if data.get("done"):
                    break

        print(flush=True)

        response_text = "".join(full_response)
        conversation.append({"role": "assistant", "content": response_text})
        return response_text

    except Exception as e:
        print(f"\n[error] Ollama: {e}", flush=True)
        return "Ollama didn't respond."


def main():
    global rag_chunks, OLLAMA_MODEL, WHISPER_MODEL_SIZE, SILENCE_THRESHOLD, MAX_TOKENS

    parser = argparse.ArgumentParser(description="VoiceLoop — local voice conversation")
    parser.add_argument("--rag", type=str, help="Folder of .md files for RAG context")
    parser.add_argument("--model", type=str, default=OLLAMA_MODEL, help="Ollama model name")
    parser.add_argument("--whisper", type=str, default=WHISPER_MODEL_SIZE,
                        choices=["tiny", "base", "small", "medium"], help="Whisper model size")
    parser.add_argument("--threshold", type=int, default=SILENCE_THRESHOLD,
                        help="Mic silence threshold (default 500)")
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                        help="Max response tokens (default 150)")
    args = parser.parse_args()

    OLLAMA_MODEL = args.model
    WHISPER_MODEL_SIZE = args.whisper
    SILENCE_THRESHOLD = args.threshold
    MAX_TOKENS = args.max_tokens

    print("=" * 50)
    print("  VOICELOOP — Local Voice Conversation")
    print(f"  LLM: {OLLAMA_MODEL}")
    print(f"  STT: Whisper {WHISPER_MODEL_SIZE} (CPU)")
    print(f"  TTS: SAPI (streaming, rate 200)")
    print(f"  Max tokens: {MAX_TOKENS}")
    if args.rag:
        print(f"  RAG: {args.rag}")
    print("  Say 'exit' or 'quit' to stop. Ctrl+C to kill.")
    print("=" * 50)

    if args.rag:
        rag_chunks = load_rag_folder(args.rag)

    init_tts()
    whisper_model = init_whisper()

    speak("Online. Talk to me.")

    while True:
        try:
            audio = record_until_silence()
            if audio is None or len(audio) < SAMPLE_RATE * 0.3:
                continue

            text = transcribe(whisper_model, audio)
            if not text or len(text.strip()) < 2:
                continue

            print(f"[you] {text}", flush=True)

            lower = text.strip().lower()
            if lower in ("exit", "quit", "stop", "shut up", "goodbye", "bye"):
                speak("Offline.")
                break

            response = query_ollama(text)
            if response:
                speak(response)

        except KeyboardInterrupt:
            print("\n[killed]", flush=True)
            break


if __name__ == "__main__":
    main()
