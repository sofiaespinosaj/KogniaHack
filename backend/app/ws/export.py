"""Exporta el contrato: JSON Schema y tipos TypeScript, ambos generados desde los modelos.

    uv run python -m app.ws.export all            # escribe backend/contract/ws-events.schema.json y ws-events.ts
    uv run python -m app.ws.export all --check    # falla si lo publicado no coincide con los modelos
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.ws import protocol as P

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contract"
SCHEMA_PATH = CONTRACT_DIR / "ws-events.schema.json"
TS_PATH = CONTRACT_DIR / "ws-events.ts"
REF = "#/$defs/{model}"


def build_schema() -> dict:
    client = TypeAdapter(P.ClientMessage).json_schema(ref_template=REF, mode="validation")
    server = TypeAdapter(P.ServerMessage).json_schema(ref_template=REF, mode="serialization")
    defs = {**client.pop("$defs"), **server.pop("$defs")}
    # `type` y `v` siempre viajan: se declaran obligatorios para que el esquema discrimine bien
    for d in defs.values():
        props = d.get("properties", {})
        if "type" in props:
            d["required"] = sorted({*d.get("required", []), "type", "v"})
    defs["ClientMessage"], defs["ServerMessage"] = client, server
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"kognia/ws-events/{P.PROTOCOL}",
        "title": "Eventos del WebSocket",
        "description": "Contrato de mensajes JSON entre el cliente y el servidor (versión %s). Los frames binarios "
                       "son audio PCM16 mono 24 kHz." % P.PROTOCOL,
        "x-protocol": P.PROTOCOL,
        "oneOf": [{"$ref": REF.format(model="ClientMessage")}, {"$ref": REF.format(model="ServerMessage")}],
        "$defs": defs,
    }


def schema_json() -> str:
    return json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------- TypeScript
def _ts_type(node: dict) -> str:
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if "const" in node:
        return json.dumps(node["const"], ensure_ascii=False)
    if "enum" in node:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in node["enum"])
    for key in ("anyOf", "oneOf"):
        if key in node:
            parts = [_ts_type(n) for n in node[key]]
            return " | ".join(dict.fromkeys(parts))
    t = node.get("type")
    if t == "array":
        inner = _ts_type(node.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t in ("integer", "number"):
        return "number"
    if t == "string":
        return "string"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "object":
        return "Record<string, unknown>" if "properties" not in node else _ts_object(node)
    return "unknown"


def _ts_object(node: dict, indent: str = "  ") -> str:
    required = set(node.get("required", []))
    lines = ["{"]
    for name, prop in node.get("properties", {}).items():
        doc = prop.get("description")
        if doc:
            lines.append(f"{indent}/** {doc} */")
        opt = "" if name in required else "?"
        lines.append(f"{indent}{name}{opt}: {_ts_type(prop)};")
    lines.append("}")
    return "\n".join(lines)


def build_ts() -> str:
    schema = build_schema()
    out = ["// GENERADO desde backend/app/ws/protocol.py — no editar a mano.",
           "// Regenerar: uv run python -m app.ws.export all (desde backend/).",
           f"// Protocolo {P.PROTOCOL}. Los frames binarios son audio PCM16 mono 24 kHz (1.920 bytes por 40 ms).", "",
           f'export const PROTOCOL_VERSION = "{P.PROTOCOL}";', ""]
    names = {"client": [c.__name__ for c in P.CLIENT_TYPES], "server": [c.__name__ for c in P.SERVER_TYPES]}
    for name in sorted(n for n in schema["$defs"] if n not in ("ClientMessage", "ServerMessage")):
        node = schema["$defs"][name]
        if node.get("type") == "object":
            doc = node.get("description")
            if doc:
                out.append(f"/** {doc} */")
            out.append(f"export interface {name} {_ts_object(node)}")
        else:
            out.append(f"export type {name} = {_ts_type(node)};")
        out.append("")
    out.append("export type ClientMessage = " + " | ".join(names["client"]) + ";")
    out.append("export type ServerMessage = " + " | ".join(names["server"]) + ";")
    out.append("export type WsMessage = ClientMessage | ServerMessage;")
    out.append("")
    out.append("/** Discriminante `type` de todos los mensajes JSON. */")
    out.append("export type MessageType = WsMessage[\"type\"];")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["schema", "ts", "all"])
    ap.add_argument("--check", action="store_true", help="no escribe: falla si lo publicado está desactualizado")
    a = ap.parse_args(argv)
    targets: list[tuple[Path, str]] = []
    if a.what in ("schema", "all"):
        targets.append((SCHEMA_PATH, schema_json()))
    if a.what in ("ts", "all"):
        targets.append((TS_PATH, build_ts()))
    stale = []
    for path, content in targets:
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if a.check:
            if current != content:
                stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"escrito {path}")
    if stale:
        print("Desactualizado: " + ", ".join(stale) + " (ejecuta: uv run python -m app.ws.export all)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
