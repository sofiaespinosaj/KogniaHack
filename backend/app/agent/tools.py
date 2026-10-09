"""Tools de consulta del agente sobre la tabla `ips` (sin SQL libre).

Cada tool traduce argumentos validados a consultas parametrizadas en DuckDB y devuelve un
resultado JSON compacto con envoltorio común. Los enums del esquema se generan desde el
perfil de datos, así que siguen a los datos tras un refresco.
"""
from __future__ import annotations

import difflib
import re
import time
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator

from app.datastore.store import DISTRICT_TO_DEPARTMENT, Store

MAX_ITEMS = 10
LIST_DEFAULT = 5          # sedes que devuelve listar_ips si no se pide n
MAX_CALLS_PER_TURN = 2
FUZZY_AUTO = 0.9          # similitud mínima para resolver sin ambigüedad una coincidencia aproximada
SUGGEST_CUTOFF = 0.6      # similitud mínima de las sugerencias de lugar

TOOL_NAMES = ("count_ips", "count_sedes", "sum_capacidad", "top_n", "group_by", "listar_ips", "buscar_ips")
METRICS = {
    "ips": "count(DISTINCT codigo_prestador)",
    "sedes": "count(DISTINCT sede_id)",
    "capacidad": "coalesce(sum(cantidad_capacidad), 0)",
}
# dimensión -> (expresión SQL de agrupación, expresión de etiqueta)
DIMENSIONS = {
    "departamento": ("departamento_canonico", "departamento_canonico"),
    "municipio": ("municipio_norm, departamento_canonico",
                  "any_value(municipio) || ', ' || departamento_canonico"),
    "naturaleza": ("naturaleza", "naturaleza"),
    "nivel_atencion": ("nivel_atencion", "'nivel ' || nivel_atencion"),
    "grupo_capacidad": ("grupo_capacidad", "grupo_capacidad"),
}
_STOPWORDS = {"de", "del", "la", "el", "los", "las", "para", "en", "y", "con", "cama", "camas"}
COVERAGE_NOTE = ("El nivel de atención casi solo está registrado para IPS públicas; "
                 "el valor es lo observado en la fuente, no un cero real.")


def norm(text: str) -> str:
    """Minúsculas y sin tildes, igual que las columnas `*_norm`."""
    t = unicodedata.normalize("NFD", text)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", norm(text))


def _stem(tok: str) -> str:
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok


# --------------------------------------------------------------------------- esquemas
def _enum(profile: dict, column: str) -> list:
    col = next(c for c in profile["columns"] if c["name"] == column)
    if not col.get("values_complete"):
        raise ValueError(f"El perfil no expone todos los valores de {column}")
    return [v["value"] for v in col["values"]]


def build_tool_schemas(profile: dict) -> list[dict]:
    """Esquemas de las siete function tools; los enums salen del perfil."""
    departamentos = sorted(_enum(profile, "departamento_canonico"))
    filters = {
        "departamento": {"type": "string", "enum": departamentos,
                         "description": "Departamento. Cali, Cartagena, etc. se cuentan dentro de su departamento."},
        "municipio": {"type": "string", "description": "Municipio, con o sin tildes."},
        "naturaleza": {"type": "string", "enum": sorted(_enum(profile, "naturaleza")),
                       "description": "Naturaleza jurídica de la IPS."},
        "nivel_atencion": {"type": "integer", "enum": sorted(_enum(profile, "nivel_atencion")),
                           "description": "Nivel de atención; casi solo existe para IPS públicas."},
    }
    grupo = {"type": "string", "enum": sorted(_enum(profile, "grupo_capacidad")),
             "description": "Grupo de capacidad instalada."}
    descripcion = {"type": "string", "description": "Descripción del ítem de capacidad, p. ej. 'adultos'."}

    def tool(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
        return {"type": "function", "name": name, "description": description,
                "parameters": {"type": "object", "properties": props,
                               "required": required or [], "additionalProperties": False}}

    dims = {"type": "string", "enum": list(DIMENSIONS)}
    metrica = {"type": "string", "enum": list(METRICS),
               "description": "ips = prestadores distintos; sedes = sedes distintas; "
                              "capacidad = suma de capacidad (requiere grupo_capacidad)."}
    ranking = {"dimension": dims, "metrica": metrica, "grupo_capacidad": grupo,
               "descripcion_capacidad": descripcion, **filters}
    return [
        tool("count_ips", "Cuenta IPS (prestadores distintos, no filas).", dict(filters)),
        tool("count_sedes", "Cuenta sedes distintas.", dict(filters)),
        tool("sum_capacidad", "Suma la capacidad instalada de un grupo (camas, consultorios, etc.).",
             {"grupo_capacidad": grupo, "descripcion_capacidad": descripcion, **filters},
             ["grupo_capacidad"]),
        tool("top_n", "Ranking de las n primeras categorías de una dimensión (máx. 10).",
             {**ranking, "n": {"type": "integer", "minimum": 1}}, ["dimension", "metrica"]),
        tool("group_by", "Agrupa por una dimensión y devuelve hasta 10 grupos.", ranking,
             ["dimension", "metrica"]),
        tool("listar_ips", "Lista sedes de IPS de un municipio o departamento con nombre, dirección, teléfono y "
                           "capacidad; sirve para saber a dónde ir. Con grupo_capacidad solo las que tienen esa "
                           "capacidad (p. ej. CAMAS o AMBULANCIAS), ordenadas de mayor a menor.",
             {"grupo_capacidad": grupo, "descripcion_capacidad": descripcion, **filters,
              "n": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS}}),
        tool("buscar_ips", "Busca una IPS por nombre de prestador o de sede.",
             {"nombre": {"type": "string", "minLength": 2, "maxLength": 100},
              "departamento": filters["departamento"], "municipio": filters["municipio"]}, ["nombre"]),
    ]


def _compact_error(err) -> dict:
    path = ".".join(str(p) for p in err.absolute_path)
    if err.validator == "enum":
        out = {"estado": "error_validacion", "error": f"valor no permitido en '{path}'"}
        if len(err.validator_value) <= MAX_ITEMS:
            out["permitidos"] = err.validator_value
        return out
    if err.validator == "additionalProperties":
        return {"estado": "error_validacion", "error": "campo desconocido: " + err.message.split("'")[1]
                if "'" in err.message else "campo desconocido"}
    if err.validator == "required":
        return {"estado": "error_validacion", "error": err.message[:80]}
    return {"estado": "error_validacion", "error": f"argumento inválido en '{path or 'argumentos'}'"}


# --------------------------------------------------------------------------- resultado
_KEEP = {"valor", "filas_usadas"}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in _KEEP and v is not None or v not in (None, "", [], {})}


# --------------------------------------------------------------------------- ejecutor
class AgentTools:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._schemas_for: dict | None = None
        self._schemas: list[dict] = []
        self._validators: dict[str, Draft202012Validator] = {}
        self.timings: dict[str, list[float]] = {n: [] for n in TOOL_NAMES}

    # esquemas ---------------------------------------------------------------
    def schemas(self) -> list[dict]:
        """Esquemas vigentes: se regeneran cuando el perfil cambia (p. ej. tras un refresco)."""
        profile = self._store.profile
        if profile is None:
            raise RuntimeError("Los datos aún no están cargados")
        if profile is not self._schemas_for:
            self._schemas = build_tool_schemas(profile)
            self._validators = {t["name"]: Draft202012Validator(t["parameters"]) for t in self._schemas}
            self._schemas_for = profile
        return self._schemas

    # entrada ----------------------------------------------------------------
    def call(self, name: str, args: dict | None) -> dict:
        """Valida y ejecuta una tool. Nunca lanza por argumentos inválidos."""
        t0 = time.perf_counter()
        try:
            self.schemas()
            if name not in self._validators:
                return {"estado": "error_validacion", "error": f"tool desconocida: {name[:40]}"}
            args = self._canonical_args(name, {k: v for k, v in (args or {}).items() if v is not None})
            errors = sorted(self._validators[name].iter_errors(args), key=lambda e: list(e.absolute_path))
            if errors:
                return _compact_error(errors[0])
            return getattr(self, "_" + name)(args)
        finally:
            if name in self.timings:
                self.timings[name].append((time.perf_counter() - t0) * 1000)

    def _canonical_args(self, name: str, args: dict) -> dict:
        """Lleva a su forma canónica los valores de lista cerrada que el modelo escribe de otra manera
        («bogota» -> «Bogotá D.C», «camas» -> «CAMAS», «publica» -> «Pública»). Si no hay coincidencia
        clara, deja el valor tal cual y la validación lo rechaza con un error compacto."""
        props = next((t["parameters"]["properties"] for t in self._schemas if t["name"] == name), {})
        out = dict(args)
        for key, value in args.items():
            enum = (props.get(key) or {}).get("enum")
            if not enum or not isinstance(value, str) or value in enum:
                continue
            q = norm(re.sub(r"^(departamento|depto\.?)\s+(de|del)\s+", "", value.strip(), flags=re.I))
            options = {norm(str(e)): e for e in enum}
            hit = options.get(q) or next((e for n, e in options.items() if n.startswith(q) and len(q) >= 4), None)
            if hit is None:
                close = difflib.get_close_matches(q, list(options), n=1, cutoff=0.8)
                hit = options[close[0]] if close else None
            if hit is not None:
                out[key] = hit
        return out

    # utilidades -------------------------------------------------------------
    def _cur(self):
        return self._store.cursor()

    def _wrap(self, estado: str, valor: Any, filtros: dict, filas: int | None, **extra) -> dict:
        prof = self._store.profile or {}
        return _clean({"estado": estado, "valor": valor, "filtros": filtros, "filas_usadas": filas,
                       "fecha_corte": prof.get("fecha_corte"), "origen": prof.get("source"), **extra})

    def _not_found(self, filtros: dict, tipo: str, sugerencias: list[str]) -> dict:
        return self._wrap("no_encontrado", None, filtros, None, no_encontrado=tipo,
                          sugerencias=sugerencias[:3])

    def _place(self, municipio: str) -> tuple[str | None, list[str]]:
        """Resuelve un municipio contra `municipio_norm`. Devuelve (norm, sugerencias)."""
        q = norm(municipio)
        cur = self._cur()
        if cur.execute("SELECT 1 FROM ips WHERE municipio_norm = ? LIMIT 1", [q]).fetchone():
            return q, []
        options = {r[0]: r[1] for r in cur.execute(
            "SELECT municipio_norm, any_value(municipio) FROM ips GROUP BY 1").fetchall()}
        close = difflib.get_close_matches(q, list(options), n=3, cutoff=SUGGEST_CUTOFF)
        return None, [options[c] for c in close]

    def _where(self, a: dict) -> tuple[str, list, dict, dict | None]:
        """Cláusula WHERE de los filtros comunes. Devuelve (sql, params, filtros, error)."""
        conds, params, filtros = [], [], {}
        if "departamento" in a:
            conds.append("departamento_canonico = ?")
            params.append(a["departamento"])
            filtros["departamento"] = a["departamento"]
        if "municipio" in a:
            mn, sugs = self._place(a["municipio"])
            filtros["municipio"] = a["municipio"]
            if mn is None:
                return "", [], filtros, self._not_found(filtros, "municipio", sugs)
            conds.append("municipio_norm = ?")
            params.append(mn)
        if "naturaleza" in a:
            conds.append("naturaleza = ?")
            params.append(a["naturaleza"])
            filtros["naturaleza"] = a["naturaleza"]
        if "nivel_atencion" in a:
            conds.append("nivel_atencion = ?")
            params.append(a["nivel_atencion"])
            filtros["nivel_atencion"] = a["nivel_atencion"]
        return (" WHERE " + " AND ".join(conds)) if conds else "", params, filtros, None

    def _districts(self, a: dict) -> list[str]:
        """Distritos absorbidos por el departamento filtrado (para `incluye_distritos`)."""
        if "departamento" not in a:
            return []
        keys = list(DISTRICT_TO_DEPARTMENT)
        rows = self._cur().execute(
            f"SELECT DISTINCT departamento FROM ips WHERE departamento_canonico = ? "
            f"AND departamento_norm IN ({', '.join('?' * len(keys))}) ORDER BY 1", [a["departamento"], *keys]
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _coverage_gap(a: dict, dimension: str | None = None) -> bool:
        nivel = "nivel_atencion" in a or dimension == "nivel_atencion"
        return nivel and a.get("naturaleza") in ("Privada", "Mixta")

    def _describe(self, a: dict, grupo: str | None, desc_norm: str | None, filtros: dict) -> tuple[str, list, dict, dict | None]:
        where, params, filtros2, err = self._where(a)
        filtros.update(filtros2)
        if err:
            return "", [], filtros, err
        extra, extra_params = [], []
        if grupo:
            extra.append("grupo_capacidad = ?")
            extra_params.append(grupo)
        if desc_norm:
            extra.append("descripcion_capacidad_norm = ?")
            extra_params.append(desc_norm)
        if extra:
            where = (where + " AND " if where else " WHERE ") + " AND ".join(extra)
        return where, params + extra_params, filtros, None

    # descripción de capacidad ----------------------------------------------
    def _resolve_descripcion(self, grupo: str, texto: str) -> tuple[str, Any]:
        """('ok', (norm, display)) | ('ambiguo', [display]) | ('no_encontrado', [display])."""
        rows = self._cur().execute(
            "SELECT descripcion_capacidad_norm, any_value(descripcion_capacidad) FROM ips "
            "WHERE grupo_capacidad = ? AND descripcion_capacidad_norm IS NOT NULL GROUP BY 1 ORDER BY 1",
            [grupo]).fetchall()
        names = {n: d for n, d in rows}
        q = norm(texto)
        if q in names:
            return "ok", (q, names[q])
        toks = [t for t in _tokens(texto) if t not in _STOPWORDS]
        q2 = " ".join(toks)
        if q2 in names:
            return "ok", (q2, names[q2])
        stems = {_stem(t) for t in toks}
        cands = [n for n in names if stems and stems <= {_stem(t) for t in _tokens(n)}]
        if not cands:
            cands = difflib.get_close_matches(q2 or q, list(names), n=MAX_ITEMS, cutoff=FUZZY_AUTO)
        if len(cands) == 1:
            return "ok", (cands[0], names[cands[0]])
        if cands:
            return "ambiguo", [names[c] for c in cands[:MAX_ITEMS]]
        sim = sorted(names, key=lambda n: -difflib.SequenceMatcher(None, q2 or q, n).ratio())
        return "no_encontrado", [names[n] for n in sim[:3]]

    # tools ------------------------------------------------------------------
    def _count(self, a: dict, metric: str) -> dict:
        where, params, filtros, err = self._describe(a, None, None, {})
        if err:
            return err
        valor, filas = self._cur().execute(
            f"SELECT {METRICS[metric]}, count(*) FROM ips{where}", params).fetchone()
        return self._numeric(a, valor, filas, filtros)

    def _numeric(self, a: dict, valor: int, filas: int, filtros: dict) -> dict:
        extra = {}
        districts = self._districts(a)
        if districts:
            extra["incluye_distritos"] = districts
        if self._coverage_gap(a):
            return self._wrap("sin_cobertura", valor, filtros, filas, nota=COVERAGE_NOTE, **extra)
        return self._wrap("ok" if filas else "sin_resultados", valor, filtros, filas, **extra)

    def _count_ips(self, a: dict) -> dict:
        return self._count(a, "ips")

    def _count_sedes(self, a: dict) -> dict:
        return self._count(a, "sedes")

    def _sum_capacidad(self, a: dict) -> dict:
        grupo, texto = a["grupo_capacidad"], a.get("descripcion_capacidad")
        desc_norm, filtros = None, {"grupo_capacidad": grupo}
        if texto:
            estado, res = self._resolve_descripcion(grupo, texto)
            filtros["descripcion_capacidad"] = texto
            if estado == "no_encontrado":
                return self._not_found(filtros, "descripcion_capacidad", res)
            if estado == "ambiguo":
                return self._wrap("ambiguo", None, filtros, None, candidatos=res)
            desc_norm, filtros["descripcion_capacidad"] = res
        where, params, filtros, err = self._describe(a, grupo, desc_norm, filtros)
        if err:
            return err
        valor, filas = self._cur().execute(
            f"SELECT {METRICS['capacidad']}, count(*) FROM ips{where}", params).fetchone()
        return self._numeric(a, valor, filas, filtros)

    def _ranking(self, a: dict, limit: int, clamped: bool, flag_truncation: bool = False) -> dict:
        dim, metric = a["dimension"], a["metrica"]
        grupo, texto = a.get("grupo_capacidad"), a.get("descripcion_capacidad")
        if metric == "capacidad" and not grupo:
            return {"estado": "error_validacion", "error": "metrica capacidad requiere grupo_capacidad"}
        desc_norm, filtros = None, {}
        if grupo:
            filtros["grupo_capacidad"] = grupo
        if texto:
            if not grupo:
                return {"estado": "error_validacion", "error": "descripcion_capacidad requiere grupo_capacidad"}
            estado, res = self._resolve_descripcion(grupo, texto)
            filtros["descripcion_capacidad"] = texto
            if estado == "no_encontrado":
                return self._not_found(filtros, "descripcion_capacidad", res)
            if estado == "ambiguo":
                return self._wrap("ambiguo", None, filtros, None, candidatos=res)
            desc_norm, filtros["descripcion_capacidad"] = res
        where, params, filtros, err = self._describe(a, grupo, desc_norm, filtros)
        if err:
            return err
        key, label = DIMENSIONS[dim]
        if dim == "nivel_atencion":
            where = (where + " AND " if where else " WHERE ") + "nivel_atencion IS NOT NULL"
        cur = self._cur()
        groups = cur.execute(
            f"SELECT {label}, {METRICS[metric]} AS v FROM ips{where} GROUP BY {key} "
            f"ORDER BY v DESC, 1 LIMIT {limit + 1}", params).fetchall()
        filas = cur.execute(f"SELECT count(*) FROM ips{where}", params).fetchone()[0]
        truncated = len(groups) > limit
        items = [{"nombre": g[0], "valor": g[1]} for g in groups[:limit]]
        filtros = {**filtros, "dimension": dim, "metrica": metric}
        extra = {}
        if clamped or (flag_truncation and truncated):
            extra["acotado"] = True
        if dim == "nivel_atencion":
            extra["nota"] = "Solo incluye filas con nivel de atención registrado."
        districts = self._districts(a)
        if districts:
            extra["incluye_distritos"] = districts
        if self._coverage_gap(a, dim):
            extra["nota"] = COVERAGE_NOTE
            return self._wrap("sin_cobertura", items, filtros, filas, **extra)
        return self._wrap("ok" if items else "sin_resultados", items, filtros, filas, **extra)

    def _top_n(self, a: dict) -> dict:
        n = a.get("n", 5)
        return self._ranking(a, min(n, MAX_ITEMS), n > MAX_ITEMS)

    def _group_by(self, a: dict) -> dict:
        return self._ranking(a, MAX_ITEMS, False, flag_truncation=True)

    def _listar_ips(self, a: dict) -> dict:
        """Sedes de un lugar con su contacto y capacidad (camas y ambulancias, o el grupo pedido)."""
        n = a.get("n", LIST_DEFAULT)
        grupo = a.get("grupo_capacidad")
        desc_norm, extra = None, {}
        if "descripcion_capacidad" in a:
            if not grupo:
                return {"estado": "error_validacion", "error": "descripcion_capacidad requiere grupo_capacidad"}
            kind, res = self._resolve_descripcion(grupo, a["descripcion_capacidad"])
            if kind != "ok":
                filtros = {"grupo_capacidad": grupo, "descripcion_capacidad": a["descripcion_capacidad"]}
                if kind == "ambiguo":
                    return self._wrap("ambiguo", None, filtros, None, candidatos=res)
                return self._not_found(filtros, "descripcion_capacidad", res)
            desc_norm = res[0]
            extra["descripcion_resuelta"] = res[1]
        where, params, filtros, err = self._describe(
            {k: v for k, v in a.items() if k in ("departamento", "municipio", "naturaleza", "nivel_atencion")},
            None, None, {})
        if err:
            return err
        if grupo:
            filtros["grupo_capacidad"] = grupo
        if desc_norm:
            filtros["descripcion_capacidad"] = a["descripcion_capacidad"]
        cap_cond = "grupo_capacidad = ?" + (" AND descripcion_capacidad_norm = ?" if desc_norm else "")
        cap_params = [grupo] + ([desc_norm] if desc_norm else []) if grupo else []
        cap = (f"coalesce(sum(cantidad_capacidad) FILTER (WHERE {cap_cond}), 0)" if grupo else
               "coalesce(sum(cantidad_capacidad) FILTER (WHERE grupo_capacidad = 'CAMAS'), 0)")
        having = " HAVING capacidad > 0" if grupo else ""
        sql = (f"SELECT any_value(nombre_sede), any_value(nombre_prestador), any_value(municipio), "
               f"any_value(departamento_canonico), any_value(naturaleza), any_value(nivel_atencion), "
               f"any_value(direccion), any_value(telefono), {cap} AS capacidad, "
               f"coalesce(sum(cantidad_capacidad) FILTER (WHERE grupo_capacidad = 'AMBULANCIAS'), 0) AS ambulancias, "
               f"count(*) AS filas FROM ips{where} GROUP BY sede_id{having} "
               f"ORDER BY capacidad DESC, ambulancias DESC, any_value(nombre_sede)")
        rows = self._cur().execute(sql, cap_params + params).fetchall()
        if not rows:
            return self._wrap("sin_resultados", [], filtros, 0, **extra)
        cap_key = (grupo or "camas").lower()

        def item(r: tuple) -> dict:
            out = {"sede": r[0], "prestador": r[1] if r[1] != r[0] else None, "municipio": r[2],
                   "departamento": r[3], "naturaleza": r[4], "nivel_atencion": r[5], "direccion": r[6],
                   "telefono": r[7], cap_key: int(r[8])}
            if cap_key != "ambulancias" and r[9]:
                out["ambulancias"] = int(r[9])
            return _clean(out)

        return self._wrap("ok", [item(r) for r in rows[:n]], filtros, sum(r[10] for r in rows),
                          total_sedes=len(rows), **extra)

    def _buscar_ips(self, a: dict) -> dict:
        q = norm(a["nombre"])
        where, params, filtros, err = self._describe(
            {k: v for k, v in a.items() if k in ("departamento", "municipio")}, None, None, {})
        if err:
            return err
        filtros["nombre"] = a["nombre"]
        cur = self._cur()
        base = where or " WHERE true"

        def find(cond: str, cparams: list) -> list[tuple]:
            return cur.execute(
                f"SELECT codigo_prestador, any_value(nombre_prestador) AS nombre, "
                f"any_value(naturaleza) AS nat, mode(departamento_canonico) AS dep, mode(municipio) AS mun, "
                f"count(DISTINCT sede_id) AS sedes, count(*) AS filas, "
                f"any_value(CASE WHEN nombre_sede_norm = nombre_prestador_norm THEN NULL ELSE nombre_sede END) AS sede "
                f"FROM ips{base} AND ({cond}) GROUP BY codigo_prestador "
                f"ORDER BY length(any_value(nombre_prestador)), nombre LIMIT 50",
                params + cparams).fetchall()

        found = find("nombre_prestador_norm = ? OR nombre_sede_norm = ?", [q, q])
        if not found:
            toks = _tokens(a["nombre"])
            if toks:
                like = " AND ".join(["{c} LIKE ?"] * len(toks))
                cond = f"({like.format(c='nombre_prestador_norm')}) OR ({like.format(c='nombre_sede_norm')})"
                found = find(cond, [f"%{t}%" for t in toks] * 2)
        if not found:  # coincidencia aproximada sobre nombres de prestador
            names = {r[0]: r[1] for r in cur.execute(
                f"SELECT nombre_prestador_norm, codigo_prestador FROM ips{base} GROUP BY 1, 2", params).fetchall()}
            close = difflib.get_close_matches(q, list(names), n=MAX_ITEMS, cutoff=FUZZY_AUTO)
            if close:
                codes = list({names[c] for c in close})
                found = find(f"codigo_prestador IN ({', '.join('?' * len(codes))})", codes)
        if not found:
            return self._wrap("sin_resultados", [], filtros, 0)

        def item(r: tuple) -> dict:
            return _clean({"nombre": r[1], "naturaleza": r[2], "departamento": r[3], "municipio": r[4],
                           "sedes": r[5], "sede": r[7]})

        filas = sum(r[6] for r in found)
        if len(found) == 1:
            return self._wrap("ok", [item(found[0])], filtros, filas)
        extra = {"total_candidatos": len(found)} if len(found) > MAX_ITEMS else {}
        return self._wrap("ambiguo", None, filtros, filas,
                          candidatos=[item(r) for r in found[:MAX_ITEMS]], **extra)


class ToolSession:
    """Una sesión de conversación: limita a dos llamadas a tools por turno de usuario."""

    def __init__(self, tools: AgentTools) -> None:
        self.tools = tools
        self._calls = 0

    def begin_turn(self) -> None:
        self._calls = 0

    def call(self, name: str, args: dict | None) -> dict:
        self._calls += 1
        if self._calls > MAX_CALLS_PER_TURN:
            return {"estado": "limite_llamadas",
                    "mensaje": "Máximo de llamadas por turno alcanzado; responde con la evidencia ya obtenida."}
        return self.tools.call(name, args)
