@echo off
echo ============================================
echo  VoiceLoop Setup — Windows
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Check pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found
    pause
    exit /b 1
)
echo [OK] pip found

:: Install dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] Some packages may have failed. Check output above.
)
echo.
echo [OK] Dependencies installed

:: Check Ollama
echo.
echo Checking Ollama...
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Ollama not found. Install from https://ollama.com
    echo        You need Ollama running with at least one model pulled.
    echo        Example: ollama pull llama3.2:3b
) else (
    echo [OK] Ollama found
)

:: Check microphone
echo.
echo Testing microphone access...
python -c "import sounddevice as sd; d = sd.query_devices(sd.default.device[0]); print(f'[OK] Mic: {d[\"name\"]}')" 2>nul
if errorlevel 1 (
    echo [WARN] No microphone detected. Plug one in before running.
)

:: Test TTS (System.Speech via PowerShell)
echo.
echo Testing Windows TTS...
powershell -NoProfile -File speak.ps1 -text "TTS test passed" 2>nul
if errorlevel 1 (
    echo [WARN] System.Speech TTS failed. Check PowerShell is available.
) else (
    echo [OK] System.Speech TTS working
)

echo.
echo ============================================
echo  Setup complete. Run with:
echo    python voiceloop.py
echo  With RAG:
echo    python voiceloop.py --rag path\to\markdown\folder
echo ============================================
pause
