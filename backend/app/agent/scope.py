"""Ámbito de Ivy: solo hospitales, clínicas e IPS de Colombia (el dataset). Filtro previo al LLM.

Si la pregunta es claramente de otro tema (películas, carros, recetas, deportes, clima, programación…) y no trae
ninguna señal de salud, se responde con una redirección amable sin llamar al modelo: así es imposible que el
modelo conteste fuera de su ámbito, y además no gasta tiempo ni cuota. Lo dudoso pasa al modelo, cuyas
instrucciones repiten la misma regla. Saludos, agradecimientos y «¿quién eres?» siempre pasan.
"""
from __future__ import annotations

import re
import unicodedata

# Señales de que la pregunta sí es del ámbito (salud, prestadores, capacidad, urgencias).
_HEALTH = ("ips", "hospital", "clinic", "salud", "sede", "cama", "ambulanc", "urgenc", "emergenc", "medic",
           "doctor", "eps", "consultori", "camilla", "sala de", "nivel de atencion", "prestador", "centro de salud",
           "puesto de salud", "atender", "atencion", "herid", "accident", "enferm", "dolor", "duele", "sintoma",
           "embaraz", "parto", "pediatr", "uci", "cuidado intensivo", "odontolog", "psiquiatr", "vacun", "cirug",
           "capacidad", "publica", "privada", "mixta", "reps", "ese ", "sangre", "farmac")

# Temas claramente ajenos.
_OFF_TOPIC = ("pelicul", "serie", "netflix", "musica", "cancion", "cantante", "receta", "cocin", "comida",
              "restaurante", "llanta", "carro", "moto ", "taller", "mecanic", "gasolina", "futbol", "partido",
              "deporte", "clima", "lluvia", "chiste", "poema", "cuento", "programar", "codigo", "python",
              "javascript", "tarea", "matematic", "ecuacion", "politic", "eleccion", "presidente", "bitcoin",
              "cripto", "acciones de", "invertir", "inversion", "viaje", "hotel", "vuelo", "videojuego",
              "horoscopo", "signo zodiacal", "novia", "novio", "ropa", "zapatos", "celular", "iphone", "wifi",
              "computador", "banco", "credito", "prestamo", "trabajo de", "empleo", "universidad", "colegio",
              "mascota", "perro", "gato", "veterinari", "farandula", "noticias", "loteria", "apuesta")

# Intentos de sacar a Ivy de su papel.
_JAILBREAK = ("ignora tus instrucciones", "ignora las instrucciones", "olvida tus instrucciones",
              "olvida tus reglas", "actua como", "finge que", "eres ahora", "modo desarrollador", "system prompt",
              "prompt del sistema", "tus instrucciones")

REDIRECTS = (
    "Eso se sale de lo que sé hacer. Yo te ayudo con hospitales y clínicas de Colombia: por ejemplo, a qué IPS "
    "ir en tu ciudad o cómo contactar una. ¿Te ayudo con algo así?",
    "Ahí no te puedo ayudar, lo mío son los hospitales y clínicas de Colombia. Si quieres, te digo qué IPS hay "
    "cerca de ti o cuántas camas tienen. ¿Qué te gustaría saber?",
    "Me encantaría, pero solo sé de hospitales y clínicas en Colombia. ¿Buscas dónde atenderte o el contacto de "
    "alguna IPS?",
)
ROLE_REPLY = ("Sigo siendo Ivy y solo puedo ayudarte con hospitales y clínicas de Colombia. ¿Qué te gustaría "
              "saber sobre ellos?")


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return " " + re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")) + " "


def off_topic_reply(text: str, turn_index: int = 0) -> str | None:
    """Respuesta de redirección si la pregunta está claramente fuera del ámbito; None si puede ser del ámbito."""
    q = _plain(text)
    if any(j in q for j in _JAILBREAK):
        return ROLE_REPLY
    if any(h in q for h in _HEALTH):
        return None
    if any(o in q for o in _OFF_TOPIC):
        return REDIRECTS[turn_index % len(REDIRECTS)]
    return None
