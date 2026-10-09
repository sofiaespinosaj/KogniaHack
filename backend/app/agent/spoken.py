"""Respuestas habladas sin LLM: el respaldo de Lumi cuando ningún modelo de Groq responde.

- `answer_from_results`: convierte los resultados de las tools ya ejecutadas en el turno en una respuesta corta,
  natural y en español (sin «el dataset dice», sin estados internos).
- `guess_tool`: si el modelo falló antes de consultar, reconoce las intenciones más comunes («¿cuántas IPS hay en
  X?», «¿qué IPS hay en X?», «¿cuántas camas…?») para consultar igual y responder con datos reales.
Todo número, nombre o dirección sale de un resultado de tool; nada se inventa.
"""
from __future__ import annotations

import re
from typing import Any

from app.agent.tools import AgentTools, norm

LIST_SHOWN = 3                     # opciones que se dicen en voz alta de una lista
_SMALL = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "por", "para", "san", "santa"}
_KEEP_UPPER = {"ips", "ese", "sas", "s.a.s", "s.a", "uci", "eps", "d.c", "d.c."}
_CAPACITY_WORDS = {"cama": "CAMAS", "ambulanc": "AMBULANCIAS", "consultori": "CONSULTORIOS", "camilla": "CAMILLAS",
                   "sala": "SALAS", "silla": "SILLAS", "unidad movil": "UNIDAD MOVIL", "unidades moviles": "UNIDAD MOVIL"}
_PLACE_PREFIX = r"(?:\ben|\bde|\bdel|\bpor|\bpara|\bcerca de|\bciudad de|\bmunicipio de|\bdepartamento de|\bdepartamento del)"


def human_name(name: str | None) -> str:
    """«HOSPITAL SANTA SOFIA DE CALDAS» -> «Hospital Santa Sofia de Caldas» (las siglas se conservan)."""
    if not name:
        return ""
    words = []
    for i, w in enumerate(str(name).split()):
        low = w.lower()
        if low in _KEEP_UPPER:
            words.append(w.upper())
        elif i > 0 and low in _SMALL - {"san", "santa"}:
            words.append(low)
        else:
            words.append(low[:1].upper() + low[1:])
    return " ".join(words)


def spoken_int(n: Any) -> str:
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else str(n)


def spoken_phone(raw: str | None) -> str:
    """Primer número del teléfono en grupos de dos y tres dígitos, separados por comas para las pausas."""
    if not raw:
        return ""
    m = re.search(r"\d[\d\s-]{5,}\d", str(raw))
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(0))
    groups, i = [], 0
    while i < len(digits):
        step = 3 if (len(digits) - i) % 2 else 2
        groups.append(digits[i:i + step])
        i += step
    return ", ".join(groups)


def short_address(raw: str | None) -> str:
    """Vía principal y barrio; sin letras de placa ni «N°»."""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", str(raw)).strip()
    text = re.split(r"\s*(?:N[°ºo]\.?|#|No\.?)\s*", text, maxsplit=1)[0]
    barrio = re.search(r"\b(?:barrio|br\.?|b/)\s+([\w\s]+)", str(raw), flags=re.I)
    via = human_name(text)
    return f"{via}, barrio {human_name(barrio.group(1).strip())}" if barrio else via


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return "; ".join(items[:-1]) + " y " + items[-1]


def _place(filtros: dict) -> str:
    if filtros.get("municipio"):
        return f" en {human_name(filtros['municipio'])}"
    if filtros.get("departamento"):
        return f" en {filtros['departamento']}"
    return " en Colombia"


def answer_one(name: str, out: dict) -> str | None:
    """Respuesta natural para el resultado de una tool; None si no hay nada útil que decir."""
    estado, filtros, valor = out.get("estado"), out.get("filtros") or {}, out.get("valor")
    if estado == "no_encontrado":
        sugs = [human_name(s) for s in out.get("sugerencias") or []]
        what = filtros.get(out.get("no_encontrado", ""), "eso")
        return (f"No encuentro {human_name(what)}. ¿Quisiste decir {' o '.join(sugs)}?" if sugs
                else f"No encuentro {human_name(what)}. ¿Me lo dices de otra forma?")
    if estado == "sin_resultados":
        return "No encontré nada con esos datos. ¿Quieres que busque en otro lugar o con otro filtro?"
    if estado == "sin_cobertura":
        return ("Ese dato casi no está registrado para las IPS privadas o mixtas; lo tengo sobre todo para las "
                "públicas.")
    if estado == "ambiguo":
        cands = out.get("candidatos") or []
        names = [human_name(c.get("nombre") if isinstance(c, dict) else c) for c in cands[:LIST_SHOWN]]
        return f"Encontré varias opciones: {_join(names)}. ¿Cuál de ellas buscas?"
    if estado != "ok":
        return None
    place = _place(filtros)
    note = " Ten en cuenta que el nivel de atención está registrado casi solo para IPS públicas." \
        if out.get("nota") and "nivel" in out["nota"] else ""
    if name == "count_ips":
        return f"Hay {spoken_int(valor)} IPS{place}.{note}"
    if name == "count_sedes":
        return f"Hay {spoken_int(valor)} sedes de IPS{place}.{note}"
    if name == "sum_capacidad":
        grupo = (filtros.get("grupo_capacidad") or "unidades").lower()
        desc = f" de {filtros['descripcion_capacidad']}" if filtros.get("descripcion_capacidad") else ""
        return f"Hay {spoken_int(valor)} {grupo}{desc}{place}.{note}"
    if name in ("top_n", "group_by") and isinstance(valor, list) and valor:
        parts = [f"{human_name(v.get('nombre'))}, con {spoken_int(v.get('valor'))}" for v in valor[:LIST_SHOWN]]
        return f"Los primeros son {_join(parts)}.{note}"
    if name == "listar_ips" and isinstance(valor, list) and valor:
        total = out.get("total_sedes", len(valor))
        names = []
        for v in valor[:LIST_SHOWN]:
            n = human_name(v.get("sede") or v.get("prestador"))
            if not filtros.get("municipio") and v.get("municipio"):
                n += f", en {human_name(v['municipio'])}"
            names.append(n)
        intro = f"Encontré {spoken_int(total)} sedes{place}" + (". Algunas son" if total > len(names) else "")
        return f"{intro}: {_join(names)}. ¿Quieres la dirección o el teléfono de alguna?{note}"
    if name == "buscar_ips" and isinstance(valor, list) and valor:
        v = valor[0]
        text = f"{human_name(v.get('nombre'))} está en {human_name(v.get('municipio'))}, {v.get('departamento', '')}."
        if v.get("direccion"):
            text += f" Queda en {short_address(v['direccion'])}."
        if spoken_phone(v.get("telefono")):
            text += f" Su teléfono es {spoken_phone(v['telefono'])}."
        return text
    return None


def answer_from_results(results: list[tuple[str, dict, dict]]) -> str | None:
    """Respuesta a partir de lo consultado en el turno (la última respuesta útil manda)."""
    for name, _args, out in reversed(results):
        text = answer_one(name, out)
        if text:
            return text
    return None


# --------------------------------------------------------------------------- intención sin LLM
def _find_place(text: str, tools: AgentTools) -> dict:
    """Municipio o departamento mencionado tras «en», «de», «ciudad de»... (evita confundir palabras comunes)."""
    q = norm(text)
    places = tools.place_names()
    best: tuple[int, dict] | None = None
    for kind in ("municipio", "departamento"):
        for key, display in places[kind].items():
            if len(key) < 4:
                continue
            m = re.search(_PLACE_PREFIX + r"\s+(?:la\s+|el\s+)?" + re.escape(key) + r"\b", q)
            if not m:
                continue
            # más largo gana; con «departamento» en la frase gana el departamento; si el nombre es de ambos
            # (Caldas, Sucre...), gana el departamento salvo que digan «ciudad» o «municipio»
            city = "ciudad" in q or "municipio" in q
            score = len(key) * 2 + (200 if "departamento" in q and kind == "departamento" else 0) \
                + (1 if (kind == "municipio") == city else 0)
            if best is None or score > best[0]:
                best = (score, {kind: display})
    return best[1] if best else {}


def guess_tool(text: str, tools: AgentTools) -> tuple[str, dict] | None:
    """Herramienta y argumentos para las preguntas más comunes, sin LLM. None si no está claro."""
    q = norm(text)
    place = _find_place(text, tools)
    grupo = next((g for w, g in _CAPACITY_WORDS.items() if w in q), None)
    if "cuant" in q:
        if grupo:
            return "sum_capacidad", {"grupo_capacidad": grupo, **place}
        if "sede" in q:
            return "count_sedes", place
        if "ips" in q or "prestador" in q or "hospital" in q or "clinica" in q or place:
            return "count_ips", place
        return None
    if place:
        args: dict[str, Any] = dict(place)
        if grupo:
            args["grupo_capacidad"] = grupo
        return "listar_ips", args
    return None
