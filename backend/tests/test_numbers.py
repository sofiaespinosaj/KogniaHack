"""Números en palabras para la voz."""
import pytest

from app.voice.numbers import number_to_words, spoken_numbers


@pytest.mark.parametrize("n,fem,expected", [
    (0, None, "cero"), (1, None, "uno"), (1, True, "una"), (1, False, "un"), (15, None, "quince"),
    (21, True, "veintiuna"), (21, False, "veintiún"), (30, None, "treinta"), (45, None, "cuarenta y cinco"),
    (100, None, "cien"), (101, None, "ciento uno"), (200, True, "doscientas"), (500, False, "quinientos"),
    (1000, None, "mil"), (1001, None, "mil uno"), (2022, None, "dos mil veintidós"),
    (9320, True, "nueve mil trescientas veinte"), (21000, True, "veintiuna mil"),
    (1_000_000, None, "un millón"), (2_500_000, None, "dos millones quinientos mil"),
])
def test_number_to_words(n, fem, expected):
    assert number_to_words(n, fem) == expected


@pytest.mark.parametrize("text,expected", [
    ("Tengo datos de 9.320 IPS y 15.547 sedes", "Tengo datos de nueve mil trescientas veinte IPS y quince mil "
                                                "quinientas cuarenta y siete sedes"),
    ("con corte al 5 de noviembre de 2022.", "con corte al cinco de noviembre de dos mil veintidós."),
    ("Hay 21 hospitales y 1 IPS.", "Hay veintiún hospitales y una IPS."),
    ("Su teléfono es 878, 25, 00.", "Su teléfono es ochocientos setenta y ocho, veinticinco, cero cero."),
    ("Llama al 8782500.", "Llama al ochocientos setenta y ocho, veinticinco, cero cero."),
    ("Calle 48 # 25-71", "Calle cuarenta y ocho número veinticinco setenta y uno"),
    ("Calle 5° N° 40-02", "Calle cinco número cuarenta cero dos"),
    ("El 45% son públicas", "El cuarenta y cinco por ciento son públicas"),
    ("en promedio 3,5", "en promedio tres coma cinco"),
    ("Bogotá D.C. tiene 1.270 IPS", "Bogotá Distrito Capital tiene mil doscientas setenta IPS"),
    ("Llama a la línea 123 ya.", "Llama a la línea uno, dos, tres ya."),
    ("Hay 123 camas", "Hay ciento veintitrés camas"),
    ("Sin números aquí.", "Sin números aquí."),
])
def test_spoken_numbers(text, expected):
    assert spoken_numbers(text) == expected
