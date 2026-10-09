"""Agente en texto para evaluar las preguntas de oro con las mismas tools e instrucciones.

Usa Chat Completions de OpenAI con function calling. La clave se lee SOLO del entorno
(`OPENAI_API_KEY`) y nunca se imprime ni se registra. El modelo se elige con
`GOLD_AGENT_MODEL` (no se fija aquí para no gastar sin querer).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

from app.agent.brief import build_brief
from app.agent.gold import GOLD, Gold, number_matches, ungrounded_numbers
from app.agent.instructions import INSTRUCTIONS
from app.agent.tools import AgentTools, ToolSession
from app.datastore.store import Store

API_URL = "https://api.openai.com/v1/chat/completions"
MAX_STEPS = 4
EVAL_HINT = "\nEn esta evaluación escribe las cifras con dígitos."


class TextAgent:
    def __init__(self, store: Store, *, api_key: str, model: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._tools = AgentTools(store)
        self._store = store
        self._model = model
        self._http = httpx.Client(headers={"Authorization": f"Bearer {api_key}"}, timeout=60.0,
                                  transport=transport)
        self._brief = build_brief(store, self._tools)

    def _tool_specs(self) -> list[dict]:
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["parameters"]}} for t in self._tools.schemas()]

    def ask(self, question: str) -> tuple[str, list[dict]]:
        """Responde una pregunta en una sesión nueva. Devuelve (texto, resultados de tools)."""
        session = ToolSession(self._tools)
        session.begin_turn()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": INSTRUCTIONS + EVAL_HINT},
            {"role": "assistant", "content": self._brief["texto"]},
            {"role": "user", "content": question},
        ]
        results: list[dict] = []
        for _ in range(MAX_STEPS):
            r = self._http.post(API_URL, json={"model": self._model, "messages": messages,
                                               "tools": self._tool_specs()})
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                return (msg.get("content") or "").strip(), results
            for c in calls:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                out = session.call(c["function"]["name"], args)
                results.append(out)
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": json.dumps(out, ensure_ascii=False)})
        return "", results

    def close(self) -> None:
        self._http.close()


def _expected_numbers(expected: Any) -> list[float]:
    if isinstance(expected, bool) or expected is None:
        return []
    if isinstance(expected, (int, float)):
        return [float(expected)]
    if isinstance(expected, (tuple, list)):
        return [n for e in expected for n in _expected_numbers(e)]
    if isinstance(expected, dict):
        return [n for e in expected.values() for n in _expected_numbers(e)]
    return []


def check_answer(g: Gold, expected: Any, text: str, results: list[dict]) -> tuple[bool, str]:
    """(ok, motivo). Cifras: todas las esperadas dichas con su redondeo. Honestidad: regla propia."""
    bad = ungrounded_numbers(text, results)
    if bad:
        return False, f"cifras sin respaldo de tool: {bad}"
    if g.kind == "cifra":
        missing = [n for n in _expected_numbers(expected) if not number_matches(text, n)]
        return (not missing, f"faltan cifras {missing}" if missing else "ok")
    ok = g.agent_check(text, expected) if g.agent_check else True
    return ok, "ok" if ok else "comportamiento de honestidad no cumplido"


def run_agent_eval(store: Store) -> int:
    key, model = os.environ.get("OPENAI_API_KEY", ""), os.environ.get("GOLD_AGENT_MODEL", "")
    if not key or not model:
        print("Faltan variables de entorno: OPENAI_API_KEY y GOLD_AGENT_MODEL", file=sys.stderr)
        return 2
    agent = TextAgent(store, api_key=key, model=model)
    cur, failures = store.cursor(), 0
    try:
        for g in GOLD:
            text, results = agent.ask(g.question)
            ok, why = check_answer(g, g.expected(cur), text, results)
            failures += not ok
            print(f"{g.id:<6}{'SI' if ok else 'NO':<4}{why:<40}{text[:120]}")
    finally:
        agent.close()
    print(f"\n{len(GOLD) - failures}/{len(GOLD)} cumplen")
    return 1 if failures else 0
