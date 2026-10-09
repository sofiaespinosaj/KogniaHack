"""La traza de eventos del MockTransport cumple el contrato que publica el backend.

La suite de TypeScript (`test_mock_transport_events.ts`) guarda en `quality/reports/mock_events_trace.json`
cada evento que emitió el mock en sus escenarios. Aquí se valida cada uno, con `jsonschema`, contra
`backend/contract/ws-events.schema.json` (generado desde los modelos Pydantic del backend). Así el mock que usa
el frontend no puede apartarse del servidor real sin que una prueba falle.
"""
from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from conftest import REPORTS, ROOT

SCHEMA = ROOT / "backend" / "contract" / "ws-events.schema.json"
TRACE = REPORTS / "mock_events_trace.json"

pytestmark = pytest.mark.contrato


@pytest.fixture(scope="module")
def trace() -> dict[str, list[dict]]:
    if not TRACE.is_file():
        pytest.skip("Falta la traza: ejecuta antes la suite TypeScript (ver quality/README de comandos)")
    return json.loads(TRACE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def server_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/ServerMessage"})


def test_traza_no_vacia(trace):
    assert sum(len(v) for v in trace.values()) > 50, "la traza debe cubrir los escenarios de la suite TS"


def test_cada_evento_del_mock_valida_contra_el_esquema(trace, server_validator):
    errores = []
    for escenario, eventos in trace.items():
        for e in eventos:
            for err in server_validator.iter_errors(e):
                errores.append(f"{escenario} seq={e.get('seq')} {e.get('type')}: {err.message[:120]}")
    assert not errores, "\n".join(errores[:20])


def test_tipos_cubiertos(trace):
    """El mock ejercita todos los mensajes de servidor que la UI necesita para la demo."""
    vistos = {e["type"] for eventos in trace.values() for e in eventos}
    esperados = {"session.state", "session.brief", "transcript.partial", "transcript.final", "agent.tool",
                 "agent.text", "audio.start", "audio.end", "audio.clear", "sentiment", "metrics"}
    assert esperados <= vistos, f"faltan: {sorted(esperados - vistos)}"


def test_sentimiento_del_mock_usa_etiquetas_reales(trace):
    from app.sentiment.analyzer import EMOTIONS, SENTIMENTS
    for eventos in trace.values():
        for e in eventos:
            if e["type"] == "sentiment":
                assert e["sentiment"] in SENTIMENTS, e
                assert e["emotion"] in EMOTIONS, e
                assert -1 <= e["score"] <= 1
