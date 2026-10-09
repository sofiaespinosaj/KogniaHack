"""Evaluación del análisis de sentimiento con frases etiquetadas a mano (tarea 4.2 de sentiment-emotion).

    uv run python -m scripts.eval_sentiment              # usa GROQ_API_KEY (o OPENAI_API_KEY) de backend/.env

Imprime, por frase, lo esperado frente a lo obtenido, los aciertos de `sentiment` y de `emotion` y la latencia
p50 frente a la meta de 2 s. Escribe el informe en `scripts/eval_sentiment_results.json`.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from app.config import load_settings_or_exit
from app.sentiment.analyzer import SentimentAnalyzer

FRASES = Path(__file__).resolve().parents[1] / "tests" / "sentiment" / "frases.json"
OUT = Path(__file__).resolve().parent / "eval_sentiment_results.json"


async def main() -> int:
    settings = load_settings_or_exit()
    if not SentimentAnalyzer.available(settings):
        print("Falta GROQ_API_KEY u OPENAI_API_KEY (o SENTIMENT_ENABLED=false).", file=sys.stderr)
        return 2
    analyzer = SentimentAnalyzer(settings, ctx=None)
    rows, lat = [], []
    for item in json.loads(FRASES.read_text(encoding="utf-8")):
        t0 = time.monotonic()
        try:
            got = await analyzer._classify(item["texto"], [])
        except Exception as e:  # noqa: BLE001
            got = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
        ms = round((time.monotonic() - t0) * 1000)
        lat.append(ms)
        rows.append({**item, "obtenido": got, "ms": ms,
                     "ok_sentiment": got.get("sentiment") == item["sentiment"],
                     "ok_emotion": got.get("emotion") == item["emotion"]})
        print(f"{'✓' if rows[-1]['ok_sentiment'] else '✗'}{'✓' if rows[-1]['ok_emotion'] else '✗'} {ms:5d} ms  "
              f"{item['texto'][:55]:55}  esperado {item['sentiment']}/{item['emotion']}  "
              f"obtenido {got.get('sentiment', '-')}/{got.get('emotion', '-')}")
        if "error" in got:
            print(f"      error: {got['error']}")
    await analyzer.close()
    report = {"modelo": SentimentAnalyzer._working or analyzer._model, "frases": len(rows),
              "aciertos_sentiment": sum(r["ok_sentiment"] for r in rows),
              "aciertos_emotion": sum(r["ok_emotion"] for r in rows),
              "latencia_p50_ms": statistics.median(lat), "meta_p50_ms": 2000, "detalle": rows}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsentiment {report['aciertos_sentiment']}/{len(rows)} · emotion {report['aciertos_emotion']}/{len(rows)}"
          f" · p50 {report['latencia_p50_ms']} ms (meta 2.000 ms) · modelo {report['modelo']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
