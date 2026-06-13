#!/bin/bash
echo "============================================"
echo " VoiceLoop Setup — Linux/macOS"
echo "============================================"
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found. Install python3."
    exit 1
fi
echo "[OK] Python found: $(python3 --version)"

# Install dependencies
echo
echo "Installing dependencies..."
pip3 install -r requirements.txt

# espeak for Linux TTS (pyttsx3 uses espeak on Linux)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo
    echo "Installing espeak-ng for Linux TTS..."
    sudo apt-get install -y espeak-ng portaudio19-dev 2>/dev/null || echo "[WARN] Install espeak-ng and portaudio manually"
fi

# Check Ollama
echo
if ! command -v ollama &> /dev/null; then
    echo "[WARN] Ollama not found. Install from https://ollama.com"
else
    echo "[OK] Ollama found"
fi

echo
echo "============================================"
echo " Setup complete. Run with:"
echo "   python3 voiceloop.py"
echo " With RAG:"
echo "   python3 voiceloop.py --rag path/to/docs"
echo "============================================"
