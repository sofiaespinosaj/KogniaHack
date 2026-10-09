"""Respuestas habladas sin LLM (respaldo de Lumi)."""
import pytest

from app.agent.spoken import answer_one, guess_tool, human_name, short_address, spoken_phone
from app.agent.tools import AgentTools
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store


@pytest.fixture(scope="module")
def tools():
    s = Store()
    assert load_snapshot(s, load_settings({}))
    return AgentTools(s)


def test_formatting_for_voice():
    assert human_name("ESE HOSPITAL SANTA SOFIA DE CALDAS") == "ESE Hospital Santa Sofia de Caldas"
    assert spoken_phone("8782500") == "878, 25, 00" and spoken_phone("8990000 ext 3214") == "899, 00, 00"
    assert spoken_phone(None) == "" and spoken_phone("sin dato") == ""
    assert short_address("CALLE 5° N° 40-02 BARRIO ASTURIAS") == "Calle 5°, barrio Asturias"
    assert short_address("Calle 48 No 25-71") == "Calle 48"


@pytest.mark.parametrize("q,expected", [
    ("Lumi, ¿cuáles son las IPs que hay en la ciudad de Manizales? Listamelas.", ("listar_ips", {"municipio": "MANIZALES"})),
    ("Necesito conocer qué IPs hay disponibles en la ciudad de Manizales", ("listar_ips", {"municipio": "MANIZALES"})),
    ("¿Cuántas IPS hay en Bogotá?", ("count_ips", {"municipio": "BOGOTÁ"})),
    ("cuántas camas hay en el departamento de Caldas", ("sum_capacidad", {"grupo_capacidad": "CAMAS", "departamento": "Caldas"})),
    ("IPS en Caldas", ("listar_ips", {"departamento": "Caldas"})),
    ("¿qué ambulancias hay en Cali?", ("listar_ips", {"municipio": "CALI", "grupo_capacidad": "AMBULANCIAS"})),
    ("me toca ir al hospital", None),                 # «toca» es un municipio, pero aquí es un verbo
    ("hola, ¿cómo estás?", None),
])
def test_guess_tool(tools, q, expected):
    assert guess_tool(q, tools) == expected


def test_answers_sound_human(tools):
    texts = [answer_one(n, tools.call(n, a)) for n, a in [
        ("listar_ips", {"municipio": "Manizales"}), ("count_ips", {"departamento": "Antioquia"}),
        ("top_n", {"dimension": "departamento", "metrica": "ips", "n": 3}),
        ("buscar_ips", {"nombre": "Avidanti Manizales"}), ("buscar_ips", {"nombre": "clinica santa maria"}),
        ("count_ips", {"municipio": "Manisales"}), ("count_ips", {"nivel_atencion": 1})]]
    assert texts[0].startswith("Encontré") and "¿Quieres la dirección o el teléfono" in texts[0]
    assert texts[1] == "Hay 837 IPS en Antioquia."
    assert texts[2].startswith("Los primeros son Bogotá D.C, con 1.270")
    assert "Su teléfono es 899, 00, 00" in texts[3]
    assert texts[4].startswith("Encontré varias opciones") and texts[4].endswith("¿Cuál de ellas buscas?")
    assert texts[5] == "No encuentro Manisales. ¿Quisiste decir Manizales o Miraflores o Manzanares?"
    assert "casi solo para IPS públicas" in texts[6]
    for t in texts:
        assert "dataset" not in t.lower() and "estado" not in t and "filtro" not in t
