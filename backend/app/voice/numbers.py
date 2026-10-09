"""Números en palabras para la voz (TTS). El texto en pantalla conserva los dígitos.

Aura-2 lee mal «9.320» (punto como decimal), los años, los teléfonos y las direcciones. Aquí se convierten a
como los diría una persona en Colombia:
- cifras con o sin separador de miles: «9.320 IPS» -> «nueve mil trescientas veinte IPS»
  (género según el sustantivo: «veintiuna sedes», «veintiún hospitales»)
- años y fechas: «5 de noviembre de 2022» -> «cinco de noviembre de dos mil veintidós»
- decimales y porcentajes: «3,5 %» -> «tres coma cinco por ciento»
- teléfonos (7 o más dígitos o grupos «878, 25, 00»): por grupos, «ochocientos setenta y ocho, veinticinco, cero cero»
- direcciones: «Calle 48 # 25-71» -> «calle cuarenta y ocho número veinticinco setenta y uno»
- siglas que se deletrean mal: «D.C.» -> «Distrito Capital»
"""
from __future__ import annotations

import re

_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
          "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
          "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
          "veintinueve"]
_TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa"}
_HUNDREDS = {100: "ciento", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos", 500: "quinientos",
             600: "seiscientos", 700: "setecientos", 800: "ochocientos", 900: "novecientos"}

# Sustantivos femeninos frecuentes en las respuestas (para «una», «veintiuna», «doscientas»).
_FEMININE = {"ips", "sedes", "sede", "camas", "cama", "ambulancias", "ambulancia", "salas", "sala", "sillas", "silla",
             "camillas", "camilla", "instituciones", "clínicas", "clinicas", "clínica", "clinica", "unidades",
             "unidad", "personas", "opciones", "opción", "horas", "veces"}


def _below_thousand(n: int, fem: bool) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    out = []
    h = n // 100 * 100
    if h:
        word = _HUNDREDS[h]
        out.append(word.replace("ientos", "ientas") if fem and h > 100 else word)
    rest = n % 100
    if rest:
        if rest < 30:
            word = _UNITS[rest]
        else:
            t, u = rest // 10 * 10, rest % 10
            word = _TENS[t] + (f" y {_UNITS[u]}" if u else "")
        out.append(word)
    return " ".join(out)


def _gender_one(text: str, fem: bool | None) -> str:
    """«uno» final: «una» ante femenino, «un» ante masculino, «uno» suelto."""
    if fem is None:
        return text
    if text.endswith("veintiuno"):
        return text[:-9] + ("veintiuna" if fem else "veintiún")
    if text.endswith("uno"):
        return text[:-3] + ("una" if fem else "un")
    return text


def number_to_words(n: int, fem: bool | None = None) -> str:
    """Entero a palabras en español. `fem`: True femenino, False masculino ante sustantivo, None suelto."""
    if n < 0:
        return "menos " + number_to_words(-n, fem)
    if n == 0:
        return "cero"
    parts = []
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    if millions:
        parts.append("un millón" if millions == 1 else _gender_one(number_to_words(millions), False) + " millones")
    if thousands:
        parts.append("mil" if thousands == 1 else _gender_one(_below_thousand(thousands, bool(fem)), bool(fem)) + " mil")
    if units:
        parts.append(_below_thousand(units, bool(fem)))
    text = " ".join(parts)
    return _gender_one(text, fem) if units else text


def _digits_spoken(group: str) -> str:
    """Grupo de un teléfono: «00» -> «cero cero», «05» -> «cero cinco», «25» -> «veinticinco»."""
    if group.startswith("0"):
        return " ".join(_UNITS[int(d)] for d in group)
    return number_to_words(int(group))


def _phone(digits: str) -> str:
    groups, i = [], 0
    while i < len(digits):
        step = 3 if (len(digits) - i) % 2 else 2
        groups.append(digits[i:i + step])
        i += step
    return ", ".join(_digits_spoken(g) for g in groups)


def _next_word(text: str, end: int) -> str:
    m = re.match(r"\s+([A-Za-zÁÉÍÓÚáéíóúÑñ]+)", text[end:])
    return m.group(1).lower() if m else ""


def spoken_numbers(text: str) -> str:
    """Convierte cifras, fechas, teléfonos y direcciones del texto a palabras para la voz."""
    if not re.search(r"\d", text):
        return re.sub(r"\bD\.\s?C\.?", "Distrito Capital", text)
    text = re.sub(r"\bD\.\s?C\.?", "Distrito Capital", text)
    text = re.sub(r"(\d)\s*%", r"\1 por ciento", text)
    text = re.sub(r"\s*(?:#|\bN[°ºo]\.?|\bNo\.)\s*(?=\d)", " número ", text)
    text = re.sub(r"(\d)\s*°", r"\1", text)
    # teléfonos ya agrupados («878, 25, 00») y números largos sin separadores
    text = re.sub(r"\b\d{3}(?:,\s\d{2,3}){2,}\b", lambda m: _phone(re.sub(r"\D", "", m.group(0))), text)
    text = re.sub(r"\b\d{7,}\b", lambda m: _phone(m.group(0)), text)
    # placas de dirección «25-71» -> «veinticinco setenta y uno»
    text = re.sub(r"\b(\d{1,3})\s*-\s*(\d{1,3})\b",
                  lambda m: f"{number_to_words(int(m.group(1)))} {_digits_spoken(m.group(2))}", text)
    # la línea de emergencias se dice dígito a dígito
    text = re.sub(r"\b(l[íi]nea(?: de emergencias)?|al|marca|marcar|llama|llamar|llamen)\s+123\b",
                  r"\1 uno, dos, tres", text, flags=re.I)

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        if "," in raw and re.fullmatch(r"\d+,\d+", raw):                 # decimal español
            a, b = raw.split(",")
            return f"{number_to_words(int(a))} coma {_digits_spoken(b) if b.startswith('0') else number_to_words(int(b))}"
        n = int(raw.replace(".", ""))
        word = _next_word(m.string, m.end())
        fem = None if not word else word in _FEMININE
        return number_to_words(n, fem)

    return re.sub(r"\d{1,3}(?:\.\d{3})+(?!\d)|\d+,\d+|\d+", repl, text)
