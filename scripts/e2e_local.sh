#!/usr/bin/env bash
# Prueba de extremo a extremo local, sin claves: OpenAI Realtime y Deepgram simulados,
# backend real (FastAPI + DuckDB con el snapshot), frontend real (Vite) y Chromium con
# un micrófono falso que dice una pregunta de oro. Uso: scripts/e2e_local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${E2E_OUT:-$(mktemp -d)}"
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

# Micrófono: 7 s de silencio, la pregunta 4.1 (24 kHz) y 8 s de silencio.
python3 - "$ROOT/backend/tests/audio/gold/4.1.wav" "$OUT/mic.wav" <<'PY'
import sys, wave
src = wave.open(sys.argv[1]); pcm = src.readframes(src.getnframes())
out = wave.open(sys.argv[2], "wb"); out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
out.writeframes(b"\0" * 2 * 24000 * 7 + pcm + b"\0" * 2 * 24000 * 8); out.close()
PY

cd "$ROOT/backend"
# VOICE_PROVIDER=groq (por defecto) u openai: E2E_PROVIDER=openai scripts/e2e_local.sh
PROVIDER="${E2E_PROVIDER:-groq}"
uv run python -m scripts.fake_services > "$OUT/fakes.log" 2>&1 & PIDS+=($!)
VOICE_PROVIDER="$PROVIDER" OPENAI_REALTIME_URL=ws://127.0.0.1:9101 DEEPGRAM_URL=ws://127.0.0.1:9102 \
  GROQ_BASE_URL=http://127.0.0.1:9103/openai/v1 DEEPGRAM_TTS_URL=http://127.0.0.1:9103/v1/speak \
  VOICE_ENABLED=true OPENAI_API_KEY=fake GROQ_API_KEY=fake DEEPGRAM_API_KEY=fake \
  CORS_ORIGINS=http://localhost:5173 DATA_PATH="$ROOT/data" \
  uv run uvicorn app.main:app --port 8000 > "$OUT/backend.log" 2>&1 & PIDS+=($!)
cd "$ROOT/frontend"
npx vite --port 5173 --strictPort > "$OUT/vite.log" 2>&1 & PIDS+=($!)

for _ in $(seq 60); do curl -sf localhost:8000/health | grep -q '"ready"' && break; sleep 1; done
for _ in $(seq 30); do curl -sf localhost:5173 > /dev/null && break; sleep 1; done

E2E_OUT="$OUT" E2E_MIC_WAV="$OUT/mic.wav" node e2e/voice.e2e.cjs
echo "Capturas y logs en $OUT"
