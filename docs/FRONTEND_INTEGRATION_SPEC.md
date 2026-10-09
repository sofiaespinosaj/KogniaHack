# Especificación de integración del Frontend (React) ⇄ Backend

> Generado el 2026-10-09 leyendo `openspec/`, `backend/`, `scripts/` y `data/` en la rama `dev` (último commit `ac45910`).
> **Fuente de verdad:** el código del backend y las specs de OpenSpec. Todo lo que no esté respaldado por ellos se marca como **[PROPUESTA]** o **[PENDIENTE]**.

---

## 0. Hallazgo crítico: el contrato de voz/tiempo real aún no existe

| Pieza | Estado |
|---|---|
| REST `GET /health`, `GET /profile`, `GET /api/brief` | **Implementado y probado** (`backend/app/main.py`, `tests/test_api.py`) |
| Tools de consulta (`count_ips`, …, `buscar_ips`) | **Implementadas**, pero solo se ejecutan en servidor; **no hay endpoint que las exponga al cliente** |
| WebSocket (`ws://`), eventos de sesión, audio, transcripción, estado del agente | **No existe.** Ninguna ruta `/ws` en el backend. El change `realtime-voice` está referenciado por `grounded-agent` y `data-ingestion` ("el contrato de eventos WebSocket se define una sola vez en `realtime-voice`") pero **no hay carpeta `openspec/changes/realtime-voice/`** |
| Transcripción diarizada y análisis de sentimiento/emociones | Exigidos en `openspec/project.md` (Reto 01), pero **ningún change los especifica** |
| Tareas abiertas en `grounded-agent/tasks.md` | 2.1 (registrar tools en sesión Realtime), 3.3 (emitir brief como respuesta inicial y datos estructurados al cliente), 5.2 (ejecutar el agente de texto con modelo real) |

**Consecuencia para el frontend:** hoy solo se puede integrar con certeza el flujo REST (brief, perfil, salud). Para voz/transcripción/insights hay que **acordar con tu compañera el change `realtime-voice`** antes de fijar eventos. La sección 5 propone un contrato provisional y la sección 6 aísla el transporte tras una interfaz para que cambiarlo cueste poco.

**Contradicción abierta a resolver con backend:** `project.md` dice STT Deepgram + LLM + TTS (pipeline), mientras `grounded-agent` asume OpenAI Realtime voz-a-voz. `config.py` exige **ambas** claves (`OPENAI_API_KEY` y `DEEPGRAM_API_KEY`) cuando `VOICE_ENABLED=true`. Esto cambia quién genera la transcripción (¿Deepgram diarizado o eventos de Realtime?) y, por tanto, los eventos WS.

---

## 1. Arquitectura detectada y dependencias

### 1.1 Stack (según `project.md` y `backend/`)

- **Backend:** FastAPI (Python ≥3.11; `.python-version` = 3.12), `uvicorn[standard]`, `httpx`, `duckdb`, `jsonschema`. Dev: `pytest`, `pytest-asyncio`.
- **Datos:** dataset SODA `s2ru-bqt6` (IPS de Colombia) → `data/snapshot.parquet` (41.427 filas, corte **2022-11-05**) cargado en DuckDB en memoria al arrancar; refresco en segundo plano solo si hay `SODA_APP_TOKEN`.
- **Agente:** 6 function tools tipadas (sin SQL libre) + instrucciones de sesión + brief determinista. Modelo configurable con `OPENAI_REALTIME_MODEL` (provisional `gpt-realtime-mini`).
- **Frontend (tu alcance):** React + Vite + TypeScript, puerto de dev `5173`. Despliegue previsto en Vercel; backend en Render/Railway/Fly con Docker (puerto `$PORT`, 8000 por defecto).
- **Un solo WebSocket por sesión** es el transporte previsto (aún sin implementar).

### 1.2 Estados de datos del backend

`GET /health` → `status`: `loading` → `ready` (normal, ≤5 s) · `degraded` (servible, conteo ≠ `snapshot.meta.json`) · `unavailable` (sin snapshot ni descarga posible). El servidor **acepta peticiones mientras carga**; `/profile` y `/api/brief` devuelven `503` hasta que haya datos.

### 1.3 Estado de ejecución local (verificado el 2026-10-09)

- `backend/.venv` existe pero está **vacío** (solo `_virtualenv.py`): **faltan todas las dependencias** (`uv sync --frozen --dry-run` lista ~35 paquetes por instalar: fastapi, uvicorn, duckdb, httpx, jsonschema, pytest…).
- No existe `backend/.env` (hay que crearlo desde `.env.example`).
- Herramientas presentes en esta máquina: `uv 0.11.16`, `Python 3.12.0`, `Node v24.14.0`, `npm 11.9.0`. Puertos `8000` y `5173` libres.
- No se ejecutó el servidor ni los tests (instalación no autorizada en esta sesión): los comandos de la §2 salen de leer el código, no de una ejecución.

---

## 2. Levantar el entorno local

> Shell: PowerShell en Windows. Raíz del repo = `Hackaton-Kognia/`.

### 2.1 Dos trampas de configuración (leídas del código)

1. **`DATA_PATH`:** el valor por defecto y el de `.env.example` es `data`, relativo al directorio de trabajo. Si arrancas desde `backend/`, busca `backend/data/` (no existe; el snapshot está en `<raíz>/data/`) → `status: "unavailable"`. **Usa `DATA_PATH=../data`** al correr desde `backend/`.
2. **`.env` no se carga solo:** `config.py` lee únicamente `os.environ`. Hay que pasar `--env-file .env` a uvicorn (o exportar las variables). Sin ello `CORS_ORIGINS` queda vacío y el navegador bloqueará las llamadas desde `http://localhost:5173`.

### 2.2 Pasos

```powershell
cd backend
uv sync                                   # instala dependencias (incluye dev)
Copy-Item .env.example .env               # .env está en .gitignore
# Edita backend/.env:  DATA_PATH=../data   (y deja VOICE_ENABLED=false por ahora)
uv run uvicorn app.main:app --port 8000 --env-file .env
```

Verificación:

```powershell
curl http://localhost:8000/health         # esperar {"status":"ready", ...} en pocos segundos
curl http://localhost:8000/api/brief      # texto + 3..5 preguntas
uv run pytest                             # (opcional) suite del backend
```

### 2.3 Variables de entorno

| Variable | Defecto | Nota |
|---|---|---|
| `DATA_PATH` | `data` | Usar `../data` desde `backend/` |
| `CORS_ORIGINS` | vacío | `http://localhost:5173` (lista separada por comas) |
| `SODA_APP_TOKEN` | — | Opcional con snapshot; sin él se omite el refresco |
| `SODA_PAGE_SIZE` / `SODA_CONCURRENCY` / `SODA_MAX_TRIES` | 1000 / 4 / 5 | Solo refresco |
| `VOICE_ENABLED` | `false` | Con `true` exige `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` (el proceso termina si faltan) |
| `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` | — | **Solo backend. Nunca en el frontend ni en `VITE_*`** |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-mini` | |

El frontend **no necesita ningún secreto**. Su única variable: `VITE_API_BASE_URL=http://localhost:8000` (y `VITE_WS_URL` cuando exista el WS).

---

## 3. Contrato REST vigente (implementado)

Base: `http://localhost:8000`. Todo JSON. CORS solo para los orígenes de `CORS_ORIGINS`.

| Método | Ruta | Éxito | Error |
|---|---|---|---|
| GET | `/health` | `200` `Health` (siempre) | — |
| GET | `/profile` | `200` `DatasetProfile` | `503` `ApiUnavailable` |
| GET | `/api/brief` | `200` `Brief` | `503` `ApiUnavailable` |

Política recomendada: al cargar la app, sondear `/health` (p. ej. cada 1 s) hasta `ready`/`degraded`; luego pedir `/api/brief` y `/profile`. Tratar `503` como "datos cargando", no como fallo fatal. En `unavailable` mostrar `error`.

---

## 4. Tipos TypeScript

Archivo sugerido: `frontend/src/api/types.ts`. Se separan los tipos **[VIGENTE]** (respaldados por código/spec) de los **[PROPUESTA]**.

### 4.1 [VIGENTE] REST

```ts
// ---- GET /health ----
export type DataStatus = "loading" | "ready" | "degraded" | "unavailable";
export type DataSource = "snapshot" | "api";

export interface Provenance {
  dataset: string;                       // "s2ru-bqt6"
  loaded_at: string | null;              // ISO 8601 UTC
  source: DataSource | null;
  rows: number;                          // 41427 en el corte actual
  fecha_corte: string | null;            // "YYYY-MM-DD" (2022-11-05)
  refresh_skipped_reason: string | null; // p. ej. "SODA_APP_TOKEN no definido"
  conversion_failures: Record<string, number>;
}
export interface Health {
  status: DataStatus;
  error: string | null;                  // nunca contiene secretos
  data: Provenance;
}

// ---- 503 de /profile y /api/brief ----
export interface ApiUnavailable { error: string; status: DataStatus }

// ---- GET /api/brief ----
export interface Brief {
  texto: string;                         // texto hablado (~20 s)
  preguntas: string[];                   // 3..5, todas respondibles con las tools
  fecha_corte: string;                   // "2022-11-05"
  origen: DataSource;
}

// ---- GET /profile ----
export interface ProfileValue { value: string | number; count: number }
export interface ProfileColumn {
  name: string; type: string;
  nulls: number; null_pct: number; distinct: number;
  values?: ProfileValue[];               // ausente en ids, contactos y *_norm
  values_complete?: boolean;             // true: todos los valores (≤50 distintos)
}
export interface DatasetProfile {
  grain: string;
  definitions: { ips: string; sedes: string };
  counting_guidance: string;
  rows: number; ips_distintas: number; sedes_distintas: number;
  columns: ProfileColumn[];
  coverage: {
    nivel_atencion: {
      null_rows: number; null_pct: number;
      rows_with_level_publica: number; rows_with_level_privada: number;
    };
    notes: string[];
  };
  naturaleza: Record<string, number>;    // Pública / Privada / Mixta -> filas
  fecha_corte: string | null;
  source: DataSource | null;
}
```

### 4.2 [VIGENTE] Tools y resultados (agent-tools)

Estos son los argumentos y resultados de las 6 tools (`backend/app/agent/tools.py`). Hoy el cliente **no** las invoca; se necesitan para tipar los resultados que el backend envíe al UI (tarjetas de evidencia, "tool call" en el drawer) y para el modo texto si se expone.

```ts
// Enums: NO hardcodear. Se derivan de /profile (columns[name].values) porque cambian con el refresco.
// Referencia del corte actual: naturaleza = "Pública"|"Privada"|"Mixta"; nivel_atencion = 1|2|3;
// grupo_capacidad = CONSULTORIOS|SALAS|CAMAS|AMBULANCIAS|CAMILLAS|UNIDAD MOVIL|SILLAS (leer exactos del perfil);
// departamento = 33 valores de `departamento_canonico`.
export type Naturaleza = string;
export type NivelAtencion = number;
export type GrupoCapacidad = string;
export type Departamento = string;

export interface CommonFilters {
  departamento?: Departamento;           // se aplica sobre departamento_canonico
  municipio?: string;                    // libre, con/sin tildes
  naturaleza?: Naturaleza;
  nivel_atencion?: NivelAtencion;
}
export type Metrica = "ips" | "sedes" | "capacidad";   // capacidad exige grupo_capacidad
export type Dimension = "departamento" | "municipio" | "naturaleza" | "nivel_atencion" | "grupo_capacidad";

export type ToolName = "count_ips" | "count_sedes" | "sum_capacidad" | "top_n" | "group_by" | "buscar_ips";

export type ToolArgs =
  | { tool: "count_ips" | "count_sedes"; args: CommonFilters }
  | { tool: "sum_capacidad"; args: CommonFilters & { grupo_capacidad: GrupoCapacidad; descripcion_capacidad?: string } }
  | { tool: "top_n"; args: CommonFilters & { dimension: Dimension; metrica: Metrica; n?: number /* ≥1, tope 10 */;
        grupo_capacidad?: GrupoCapacidad; descripcion_capacidad?: string } }
  | { tool: "group_by"; args: CommonFilters & { dimension: Dimension; metrica: Metrica;
        grupo_capacidad?: GrupoCapacidad; descripcion_capacidad?: string } }
  | { tool: "buscar_ips"; args: { nombre: string /* 2..100 */; departamento?: Departamento; municipio?: string } };

export type ToolEstado =
  | "ok" | "sin_resultados" | "no_encontrado" | "ambiguo" | "sin_cobertura"
  | "error_validacion"          // argumento fuera de esquema (resultado reducido: solo estado + error)
  | "limite_llamadas";          // >2 llamadas por turno (resultado reducido: estado + mensaje)

export interface RankingItem { nombre: string; valor: number }
export interface IpsCandidate {
  nombre: string; naturaleza?: string; departamento?: string; municipio?: string;
  sedes?: number; sede?: string;
}

// Envoltorio común. Los campos vacíos/nulos NO se envían: todo salvo `estado` es opcional.
export interface ToolResult {
  estado: ToolEstado;
  valor?: number | RankingItem[] | IpsCandidate[];  // número: count_*/sum_capacidad · RankingItem[]: top_n/group_by · IpsCandidate[]: buscar_ips ok (1 elemento) o sin_resultados ([])
  filtros?: Record<string, string | number>;         // incluye dimension/metrica en rankings
  filas_usadas?: number;
  fecha_corte?: string;                              // "2022-11-05"
  origen?: DataSource;
  incluye_distritos?: string[];                      // p. ej. ["Cali","Buenaventura"] con Valle del Cauca
  no_encontrado?: "municipio" | "descripcion_capacidad";
  sugerencias?: string[];                            // ≤3, con no_encontrado
  candidatos?: string[] | IpsCandidate[];            // con ambiguo (≤10): strings en descripcion_capacidad, objetos en buscar_ips
  total_candidatos?: number;                         // si hay más de 10
  acotado?: boolean;                                 // resultado recortado a 10
  nota?: string;                                     // p. ej. cobertura de nivel_atencion
  // solo en estados de error:
  error?: string; permitidos?: Array<string | number>; mensaje?: string;
}
```

Reglas de UI derivadas de las specs:
- `sin_cobertura` ⇒ `valor` es lo **observado**, no un cero real: mostrar `nota`, nunca "0 IPS".
- `no_encontrado` ⇒ sin `valor`; ofrecer `sugerencias` como chips clicables.
- `ambiguo` ⇒ sin `valor`; ofrecer `candidatos` para elegir.
- `sin_resultados` ⇒ `valor` = 0 con filtros válidos.
- Departamento con distritos (`incluye_distritos`) ⇒ mostrar la aclaración.
- Formato numérico es-CO (`9.320`); citar `fecha_corte` una vez, no en cada tarjeta.

### 4.3 [PROPUESTA — NO CONTRACTUAL] WebSocket

Nada de esto está en el repo. Es el conjunto mínimo que el UI necesita para cubrir `project.md` y `session-brief` ("entregar al cliente el texto del brief y las preguntas en datos estructurados"). **Acordar con backend y formalizar en `openspec/changes/realtime-voice/`.**

```ts
// Ruta sugerida: ws://localhost:8000/ws  (un WS por sesión)
export type AgentState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";

export type ServerEvent =
  | { type: "session.ready"; model?: string }
  | { type: "brief"; texto: string; preguntas: string[]; fecha_corte: string; origen: DataSource } // mismo shape que Brief
  | { type: "agent.state"; state: AgentState }
  | { type: "transcript.partial"; id: string; speaker: string; text: string; ts: number }
  | { type: "transcript.final";   id: string; speaker: string; text: string; ts: number }
  | { type: "agent.text.delta"; id: string; delta: string }
  | { type: "agent.audio"; /* chunk de audio: formato por definir */ }
  | { type: "tool.call";   id: string; name: ToolName; args: Record<string, unknown> }
  | { type: "tool.result"; id: string; name: ToolName; result: ToolResult }
  | { type: "insight"; id: string; sentiment?: "positivo" | "neutral" | "negativo"; emotions?: Record<string, number> }
  | { type: "error"; code: string; message: string };

export type ClientEvent =
  | { type: "audio.chunk"; /* PCM/opus: formato por definir */ }
  | { type: "text.question"; text: string }   // para preguntas sugeridas / modo teclado
  | { type: "interrupt" }                     // barge-in
  | { type: "session.end" };
```

Preguntas abiertas que bloquean el contrato: formato de audio (PCM16 24 kHz vs opus), si el audio del agente va por el WS o por WebRTC directo a OpenAI, quién diariza (Deepgram), esquema de `insight`, y si `tool.call/result` se reenvían al cliente (el spec dice que no se expone SQL ni credenciales, pero sí `ToolResult`).

---

## 5. Hoja de ruta del frontend

Estructura objetivo en `frontend/` (Vite + React + TS). Capa de transporte desacoplada: la UI depende de una interfaz `AgentTransport`, no del WS concreto.

```ts
interface AgentTransport {
  connect(): Promise<void>;
  sendText(text: string): void;
  sendAudio(chunk: ArrayBuffer): void;
  interrupt(): void;
  close(): void;
  on(handler: (e: ServerEvent) => void): () => void;
}
```

Implementaciones: `MockTransport` (Fase 1–3, sin backend de voz), `WsTransport` (Fase 4).

| Fase | Objetivo | Entregables | Depende de | Listo cuando |
|---|---|---|---|---|
| **0. Scaffolding** | Proyecto base | `npm create vite@latest frontend -- --template react-ts`; ESLint, Vitest + Testing Library, alias `@/`; `.env.example` con `VITE_API_BASE_URL`; `src/api/types.ts` (§4.1–4.2) | — | `npm run dev` en `:5173`, `lint`/`test`/`build` verdes |
| **1. Capa REST + salud** | Consumir lo ya implementado | Cliente `fetch` tipado; hook `useHealth` (polling hasta `ready`); `useBrief`, `useProfile`; manejo `503`/`degraded`/`unavailable`; pantalla de carga | Backend REST (§2) | App muestra brief real desde `/api/brief` |
| **2. Brief y preguntas sugeridas** | Primer impacto de la demo (criterio UX 25 %) | Componente `Brief` (texto, fecha de corte, origen); chips de `preguntas`; indicación visible de límites ("corte 5 nov 2022", nivel de atención casi solo público) | Fase 1 | Brief y 3–5 chips visibles al abrir; clic en chip llama a `sendText` |
| **3. Estados del agente + visualizador interactivo** | Feedback de voz y latencia (criterio 20 %) | Máquina de estados `AgentState`; orbe/visualizador con Web Audio `AnalyserNode` (mic y salida), reacciona a `listening/thinking/speaking`; botón mic/mute/interrupt; permisos de micrófono | `MockTransport` | Visualizador animado por estado con transporte simulado |
| **4. Integración WebSocket** | Voz real extremo a extremo | `WsTransport` (reconexión con backoff, heartbeat, cierre limpio); captura de mic con `AudioWorklet` y envío de chunks; reproducción del audio del agente con cola y corte en `interrupt` | **Contrato `realtime-voice` aprobado** | Pregunta por voz → respuesta hablada con el brief como saludo inicial |
| **5. Transcripción e insights** | Diarización + sentimiento (criterio 15 %) | Drawer con transcripción en vivo: parciales/finales, un color por hablante, auto-scroll; panel de sentimiento/emociones (línea de tiempo + estado actual); pestaña "Evidencia" con `ToolResult` (estado, valor, filtros, `fecha_corte`, `origen`, `nota`, sugerencias/candidatos clicables) | Fase 4 + eventos `transcript.*`/`insight` | Transcripción diarizada y panel de sentimiento actualizándose en vivo |
| **6. Pulido y despliegue** | Entregable (criterio 10 %) | Estados vacíos/error, a11y (teclado, `aria-live` en transcripción), responsive; `vercel.json`; `VITE_*` de producción; sección del README sobre qué se generó con IA | Todas | Build en Vercel funcionando contra el backend desplegado sin instalación local |

Notas de implementación:
- Mientras no exista WS, las Fases 1–3 son 100 % entregables con REST + `MockTransport`.
- Proxy de dev opcional en `vite.config.ts` (`/api`, `/health`, `/profile` → `:8000`) evita depender de CORS en local; igual en producción debe configurarse `CORS_ORIGINS` con la URL de Vercel.
- No introducir ningún secreto en `VITE_*`: se empaqueta en el bundle público.
- Enums de filtros: construirlos desde `/profile` al iniciar, no hardcodear.

---

## 6. Resumen de decisiones pendientes con backend

1. Crear y acordar `openspec/changes/realtime-voice/` con: ruta WS, eventos, formato de audio, barge-in.
2. Definir quién produce la transcripción diarizada y el esquema de sentimiento/emociones (hoy sin spec ni código).
3. Resolver Deepgram + pipeline vs. OpenAI Realtime voz-a-voz (§0).
4. Corregir `.env.example` / README: `DATA_PATH=data` falla al correr desde `backend/`, y `cp .env.example .env` no carga el archivo sin `--env-file`.
5. Decidir si `tool.result` se reenvía al cliente para la pestaña de evidencia.
