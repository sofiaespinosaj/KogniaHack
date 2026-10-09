"""Sentimiento y emoción de cada enunciado humano (change `sentiment-emotion`).

Corre fuera de la ruta de voz: se dispara cuando el servidor emite un `transcript.final` de una persona y
emite el evento `sentiment` del contrato cuando termina. Nunca bloquea ni rompe la sesión: con un tiempo
máximo de 3 s y cualquier fallo (red, cuota, JSON inválido) simplemente no se emite nada y se registra.

Modelo: uno de texto pequeño con salida JSON validada aquí contra listas cerradas. Con Groq
(`GROQ_SENTIMENT_MODEL`, por defecto `llama-3.1-8b-instant`, cuota propia) o, si no hay clave de Groq, OpenAI
(`OPENAI_SENTIMENT_MODEL`). Limitación declarada: se analiza solo el texto, sin tono de voz.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
import unicodedata
from typing import Any

import httpx

from app.config import Settings
from app.ws import protocol as P

log = logging.getLogger(__name__)

SENTIMENTS = ("positivo", "neutro", "negativo")
EMOTIONS = ("interés", "curiosidad", "confusión", "frustración", "sorpresa", "enojo", "alegría", "neutralidad")
TIMEOUT_S = 3.0
PER_SESSION = 2              # análisis simultáneos por sesión
MAX_WAITING = 2              # en espera por sesión; si llegan más se descarta el más antiguo
GLOBAL_LIMIT = 6             # análisis simultáneos en el proceso
CONTEXT_UTTERANCES = 2
SHORT_WORDS = 3
NEUTRAL_RANGE = 0.3
FILLERS = {"eh", "ah", "mm", "mmm", "aja", "aha", "ok", "okay", "vale", "bueno", "listo", "si", "no", "ajá", "sí"}
OPENAI_BASE = "https://api.openai.com/v1"

SYSTEM = (
    "Clasificas el sentimiento y la emoción de UN enunciado de una persona que habla con una asistente de voz "
    "sobre hospitales y clínicas (IPS) de Colombia. Usa el contexto solo para entender el enunciado. "
    "Responde únicamente un objeto JSON con las claves sentiment, emotion y score. "
    f"sentiment: uno de {', '.join(SENTIMENTS)}. emotion: una de {', '.join(EMOTIONS)}. "
    "score: número entre -1 y 1 (positivo > 0, negativo < 0, neutro cerca de 0). "
    "Una pregunta normal sin carga emocional es neutro con interés o curiosidad."
)

_global_sem: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _global_sem
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(GLOBAL_LIMIT)
    return _global_sem


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower().strip())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


_SENT_ALIASES = {"positive": "positivo", "positiva": "positivo", "neutral": "neutro", "neutra": "neutro",
                 "negative": "negativo", "negativa": "negativo"}
_EMO_BY_PLAIN = {_plain(e): e for e in EMOTIONS} | {"interest": "interés", "curiosity": "curiosidad",
                                                     "confusion": "confusión", "frustration": "frustración",
                                                     "surprise": "sorpresa", "anger": "enojo", "joy": "alegría",
                                                     "neutral": "neutralidad", "neutro": "neutralidad"}


def validate(raw: Any) -> dict:
    """Valida la salida del modelo contra las listas cerradas. Lanza ValueError si no sirve."""
    if not isinstance(raw, dict):
        raise ValueError("no es un objeto")
    sent = _plain(str(raw.get("sentiment", "")))
    sent = _SENT_ALIASES.get(sent, sent)
    emo = _EMO_BY_PLAIN.get(_plain(str(raw.get("emotion", ""))))
    if sent not in SENTIMENTS or emo is None:
        raise ValueError("valor fuera de la lista")
    try:
        score = float(raw.get("score", 0))
    except (TypeError, ValueError):
        raise ValueError("score no numérico") from None
    score = max(-1.0, min(1.0, score))
    if sent == "positivo":                       # coherencia del puntaje con el sentimiento
        score = score if score > 0 else 0.3
    elif sent == "negativo":
        score = score if score < 0 else -0.3
    else:
        score = max(-NEUTRAL_RANGE, min(NEUTRAL_RANGE, score))
    return {"sentiment": sent, "emotion": emo, "score": round(score, 2)}


def is_trivial(text: str) -> bool:
    words = [w for w in _plain(text).replace("?", " ").replace("¿", " ").replace(",", " ").replace(".", " ").split()]
    return len(words) < SHORT_WORDS or all(w in FILLERS for w in words)


class SentimentAnalyzer:
    def __init__(self, settings: Settings, ctx, *, http: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self.ctx = ctx
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        if settings.groq_api_key:
            self._url = f"{settings.groq_base_url}/chat/completions"
            self._model = settings.groq_sentiment_model
            self._key = settings.groq_api_key
        else:
            self._url = f"{OPENAI_BASE}/chat/completions"
            self._model = settings.openai_sentiment_model
            self._key = settings.openai_api_key
        self._session_sem = asyncio.Semaphore(PER_SESSION)
        self._waiting: collections.deque[asyncio.Task] = collections.deque()
        self._tasks: set[asyncio.Task] = set()
        self._history: collections.deque[tuple[str, str]] = collections.deque(maxlen=CONTEXT_UTTERANCES)
        self.latencies_ms: list[float] = []

    @staticmethod
    def available(settings: Settings) -> bool:
        return settings.sentiment_enabled and bool(settings.groq_api_key or settings.openai_api_key)

    def submit(self, final: dict) -> None:
        """Se llama justo después de emitir un `transcript.final` humano. Nunca bloquea."""
        text = (final.get("text") or "").strip()
        if not text or final.get("speaker") == "agent":
            return
        context = list(self._history)
        self._history.append((final.get("speaker", "user"), text))
        task = asyncio.create_task(self._run(final, text, context, time.monotonic()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._waiting.append(task)
        while len(self._waiting) > MAX_WAITING:   # ráfaga: se descarta el pendiente más antiguo
            old = self._waiting.popleft()
            if not old.done():
                old.cancel()
                log.info("Análisis de sentimiento descartado por ráfaga")

    async def _run(self, final: dict, text: str, context: list[tuple[str, str]], t0: float) -> None:
        try:
            if is_trivial(text):
                result = {"sentiment": "neutro", "emotion": "neutralidad", "score": 0.0}
            else:
                async with self._session_sem, _sem():
                    task = asyncio.current_task()
                    if task in self._waiting:              # ya no está en espera: no se descarta
                        self._waiting.remove(task)
                    result = await asyncio.wait_for(self._classify(text, context), TIMEOUT_S)
            ms = (time.monotonic() - t0) * 1000
            self.latencies_ms.append(ms)
            await self.ctx.emit(P.Sentiment, turn_id=final["turn_id"], utt_id=final["utt_id"],
                                speaker=final.get("speaker", "user"), **result)
            log.info("Sentimiento de %s en %d ms: %s/%s", final["utt_id"], ms, result["sentiment"], result["emotion"])
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            log.warning("Sentimiento: tiempo agotado (%s s) en %s", TIMEOUT_S, final.get("utt_id"))
        except Exception as e:  # noqa: BLE001 - fallo silencioso: nunca afecta la voz ni la UI
            log.warning("Sentimiento: fallo %s en %s", type(e).__name__, final.get("utt_id"))
        finally:
            task = asyncio.current_task()
            if task in self._waiting:
                self._waiting.remove(task)

    async def _classify(self, text: str, context: list[tuple[str, str]]) -> dict:
        ctx_lines = "\n".join(f"- {who}: {t}" for who, t in context) or "(sin contexto previo)"
        user = f"Contexto (enunciados anteriores):\n{ctx_lines}\n\nENUNCIADO a clasificar: {text}"
        body = {"model": self._model, "temperature": 0, "max_tokens": 60, "stream": False,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        r = await self._http.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"},
                                  timeout=TIMEOUT_S)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        content = r.json()["choices"][0]["message"]["content"]
        return validate(json.loads(content))

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._own_http:
            await self._http.aclose()
