import pytest

from app.datastore.store import RAW_COLUMNS


def raw_row(i: int, **over) -> dict:
    row = {k: None for k in RAW_COLUMNS}
    row.update({
        ":id": f"row-{i}",
        "departamento": "Antioquia", "municipio": "Medellín",
        "c_digo_prestador": f"P{i % 3}", "nombre_prestador": "Clínica Ñandú",
        "naturaleza": "Pública", "num_nivel_atencion": "1",
        "c_digo_sede": f"S{i}", "n_mero_sede": "1", "nom_sede_ips": "Sede Principal",
        "nom_grupo_capacidad": "CAMAS", "nom_descripcion_capacidad": "Hospitalización",
        "num_cantidad_capacidad_instalada": "10",
        "fecha_corte": "Fecha corte REPS: Nov 05 2022  1:44PM",
    })
    row.update(over)
    return {k: v for k, v in row.items() if v is not None}  # SODA omite los nulos


@pytest.fixture
def rows():
    return [raw_row(i) for i in range(50)]
