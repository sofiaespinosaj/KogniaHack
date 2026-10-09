"""Brief de sesión: texto hablado breve y preguntas sugeridas, derivados del perfil.

Determinista: el mismo perfil (y los mismos datos) produce el mismo brief. No incluye nada
que no esté en el perfil. La emisión como respuesta inicial de Realtime pertenece a
`realtime-voice` y no se implementa aquí.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.tools import AgentTools
from app.datastore.store import Store

MIN_QUESTIONS, MAX_QUESTIONS = 3, 5
SPOKEN_MAX_SECONDS = 20
WORDS_PER_SECOND = 2.5   # conservador (~150 palabras/min) para español hablado

_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"]
# La cobertura de nivel de atención se declara solo si el perfil la respalda.
_COVERAGE_RATIO = 0.01


@dataclass(frozen=True)
class SuggestedQuestion:
    pregunta: str
    tool: str
    args: tuple  # tupla de pares para ser inmutable y comparable


def _q(pregunta: str, tool: str, **args) -> SuggestedQuestion:
    return SuggestedQuestion(pregunta, tool, tuple(sorted(args.items())))


# Candidatas en orden de preferencia; solo se usan las que las tools resuelven con estado ok.
CANDIDATES = [
    _q("¿Cuántas IPS hay en total?", "count_ips"),
    _q("¿A qué IPS puedo ir en Manizales?", "listar_ips", municipio="Manizales"),
    _q("¿Qué departamento tiene más IPS?", "top_n", dimension="departamento", metrica="ips", n=1),
    _q("¿Cuántas IPS hay en Medellín?", "count_ips", municipio="Medellín"),
    _q("¿Cuántas camas de adultos hay en Antioquia?", "sum_capacidad", grupo_capacidad="CAMAS",
       descripcion_capacidad="Adultos", departamento="Antioquia"),
    _q("¿Cuántas IPS públicas son de nivel 3?", "count_ips", naturaleza="Pública", nivel_atencion=3),
]


def format_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_date(iso: str) -> str:
    y, m, d = (int(p) for p in iso.split("-"))
    return f"{d} de {_MONTHS[m - 1]} de {y}"


def estimate_spoken_seconds(text: str) -> float:
    """Estimación por palabras; las cifras largas se hablan con varias palabras."""
    words = 0
    for tok in re.findall(r"[\w.]+", text):
        if re.fullmatch(r"\d{1,3}(\.\d{3})+|\d{4,}", tok):
            words += 4   # "nueve mil trescientos veinte"
        else:
            words += 1
    return words / WORDS_PER_SECOND


def _nivel_cubierto_solo_publicas(profile: dict) -> bool:
    c = profile["coverage"]["nivel_atencion"]
    publica, privada = c["rows_with_level_publica"], c["rows_with_level_privada"]
    return publica > 0 and privada / (publica + privada) < _COVERAGE_RATIO


def build_spoken_text(profile: dict) -> str:
    """Saludo hablado: cálido, corto y que invite a conversar (decisión de producto). La fecha de corte va en el
    campo `fecha_corte` (la UI la muestra) y las limitaciones las explica Ivy en la conversación cuando aplican."""
    return (
        "¡Hola! Soy Ivy, y estoy aquí para ayudarte a encontrar hospitales y clínicas en Colombia. "
        "Puedo decirte a dónde ir en tu ciudad, cómo contactar una clínica o cuántas camas y ambulancias "
        "hay cerca de ti. Cuéntame, ¿en qué te puedo ayudar hoy?"
    )


def build_brief(store: Store, tools: AgentTools) -> dict:
    """Brief desde el perfil vigente; las preguntas se validan ejecutándolas contra las tools."""
    profile = store.profile
    if profile is None:
        raise RuntimeError("Los datos aún no están cargados")
    valid = [c for c in CANDIDATES if tools.call(c.tool, dict(c.args)).get("estado") == "ok"]
    return {
        "texto": build_spoken_text(profile),
        "preguntas": [c.pregunta for c in valid[:MAX_QUESTIONS]],
        "fecha_corte": profile["fecha_corte"],
        "origen": profile["source"],
    }


def validate_suggested(tools: AgentTools) -> list[tuple[str, int, str]]:
    """(pregunta, llamadas, estado) de cada candidata: una o dos llamadas con estado ok."""
    out = []
    for c in CANDIDATES:
        r = tools.call(c.tool, dict(c.args))
        out.append((c.pregunta, 1, r.get("estado", "?")))
    return out


class BriefCache:
    """Brief en memoria, reconstruido cuando cambia el perfil (p. ej. tras un refresco)."""

    def __init__(self, store: Store, tools: AgentTools) -> None:
        self._store, self._tools = store, tools
        self._for_profile: dict | None = None
        self._brief: dict | None = None

    def get(self) -> dict:
        if self._store.profile is not self._for_profile or self._brief is None:
            self._brief = build_brief(self._store, self._tools)
            self._for_profile = self._store.profile
        return self._brief
