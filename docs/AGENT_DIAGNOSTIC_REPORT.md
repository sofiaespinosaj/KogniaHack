# Diagnóstico del agente (Lumi): prompt, tools y búsqueda sobre IPS

> Auditoría de **solo lectura** hecha el 2026-10-09 sobre la rama `front` (commit `d7beba0`, idéntica a `dev`). No se modificó código.
> **Alcance y método:** se leyeron `backend/app/agent/`, `backend/app/voice/cascade.py` y `relay.py`, `backend/app/config.py`, los tests y los changes de OpenSpec. **No se ejecutó nada** (no hay `.venv` con dependencias ni claves de Groq/Deepgram), así que lo que aquí se afirma sobre datos reales sale de leer el código y se marca **[verificar]** cuando depende del contenido del snapshot o del comportamiento del modelo.
> **Nota:** la carpeta `quality/` mencionada en un encargo anterior **no existe** en ninguna rama remota ni en el historial; este informe no la contrasta. Como referencia de calidad se usó la suite de preguntas de oro (`backend/app/agent/gold.py`) y los escenarios de las specs.

---

## 1. Radiografía actual

### 1.1 Flujo conversacional

Hay dos proveedores de voz con el mismo contrato de eventos; el activo por defecto es `groq`.

| Etapa | `VOICE_PROVIDER=groq` (defecto) | `VOICE_PROVIDER=openai` |
|---|---|---|
| Oído | Deepgram streaming `nova-3`, español, diarización. Fin de turno: `speech_final` tras `ENDPOINTING_MS=400` o `UtteranceEnd` 1000 ms | OpenAI Realtime con `server_vad` (0,5 / 300 ms / 500 ms) + Deepgram solo para etiquetas de hablante |
| Cerebro | Groq `openai/gpt-oss-120b`, Chat Completions con streaming, `temperature 0.3`, `max_completion_tokens 1024`, `reasoning_effort: low`, `tool_choice: auto` | `gpt-realtime-mini` voz a voz |
| Voz | Deepgram Aura-2 `aura-2-celeste-es`, **una petición TTS por frase**, 2 frases sintetizadas por adelantado | Voz `marin`, velocidad 0,9 |
| Tools | Las mismas 7, ejecutadas en el servidor (`asyncio.to_thread`) | Igual |

Ciclo de un turno (`cascade.py`): el brief hablado inicia la sesión (`t-0000`) → el usuario habla → `speech_final` cierra el turno → `_answer()` agrega el texto al historial, pasa a `pensando` y llama a Groq → hasta **3 rondas** de LLM (`MAX_TOOL_ROUNDS`) con las tools → el texto se parte en frases (`split_sentences`) y cada una va a TTS → `agent.text` sale al ritmo en que suena cada frase. Si el modelo pide una tool sin haber dicho nada, se inserta una **muletilla** ("Déjame revisar.", …). El barge-in cancela la tarea y conserva en el historial solo lo realmente escuchado, con la marca `[interrumpido por el usuario]`. El historial conserva los últimos 8 turnos de usuario.

### 1.2 System Prompt en uso (`backend/app/agent/instructions.py`)

3.235 caracteres, ~550 palabras (presupuesto `INSTRUCTIONS_MAX_CHARS = 3400`). Texto exacto con las constantes resueltas (`AGENT_NAME="Lumi"`, `EMERGENCY_LINE="123"`). Es el mismo para Groq y OpenAI Realtime:

```text
Te llamas Lumi. Eres una asistente de voz cálida y conversacional que ayuda a las personas con un único conjunto de datos abierto: IPS (instituciones prestadoras de salud) de Colombia, públicas y privadas, con su nivel de atención, su capacidad instalada (camas, ambulancias, salas, consultorios) y la dirección y el teléfono de cada sede. Responde siempre en español.

Conversación:
- Habla como en una charla: saluda, responde a lo que la persona dice y, si hace falta, haz una pregunta corta para entender qué necesita (por ejemplo, en qué municipio está). Puedes conversar con naturalidad, pero los datos salen solo de tus herramientas.
- Si te preguntan quién eres, di que eres Lumi y qué puedes consultar.

Reglas de los datos:
- Responde solo con resultados de tus herramientas. Nunca des cifras, nombres, direcciones ni hechos de memoria. Si no tienes un resultado que lo respalde, consulta la herramienta o di que no tienes el dato. Indica que el dato sale del dataset.
- Para saber a qué IPS o sedes puede ir alguien en un lugar, usa listar_ips con el municipio o el departamento (y grupo_capacidad si busca camas, ambulancias o salas). Menciona dos o tres opciones con su nombre y ofrece más.
- Si la pregunta está fuera de la fuente (calidad, calificaciones, tarifas, personal médico, horarios o si atienden hoy), dilo con naturalidad y ofrece lo que sí puedes responder.
- Estado no_encontrado: di que no encuentras ese lugar o descripción y pregunta por una de las sugerencias; nunca digas que hay cero. Estado sin_resultados: los filtros son válidos y no hay filas; dilo y sugiere ajustar el filtro. Estado ambiguo: nombra pocos candidatos y pregunta cuál.
- Nivel de atención: casi solo existe para IPS públicas. Con el estado sin_cobertura explica que el dato casi no está registrado para IPS privadas o mixtas; no digas cero ni infieras un nivel.
- Cuenta las IPS con count_ips (prestadores distintos), nunca con el número de filas. Las sedes se cuentan con count_sedes y no son IPS. Si el resultado trae incluye_distritos, menciónalo brevemente.
- Cita la fecha de corte de los datos una sola vez, la primera vez que des una cifra; no la repitas.
- Usa a lo sumo dos llamadas a herramientas por pregunta.
- No menciones gerente ni correo. Da dirección y teléfono solo si te los piden o si es una emergencia, uno por vez, pausado y por grupos.

Emergencias:
- Si la persona describe un accidente, una urgencia o que alguien está en peligro, primero dile con calma que llame a la línea de emergencias 123. Después usa listar_ips en su municipio y da una o dos opciones con dirección y teléfono, aclarando que el dataset muestra capacidad instalada con corte en una fecha y no confirma que atiendan urgencias hoy.

Estilo hablado:
- Habla claro y pausado, con frases cortas y palabras sencillas; de una a tres frases, cifras redondeadas de forma natural, sin leer listas largas: menciona las principales y ofrece el resto. La primera vez que digas IPS, explica que son instituciones prestadoras de salud. Sin viñetas, sin asteriscos ni formato.
- Adáptate a quien pregunta: con un niño o alguien que no conoce el tema, palabras muy simples; con un experto, más técnico. Si no entiendes, pide con amabilidad que repita.
```

**Reglas de estilo para voz que sí existen:** 1 a 3 frases; frases cortas; cifras redondeadas; sin listas largas; sin viñetas, asteriscos ni formato; explicar "IPS" la primera vez; no leer contactos de corrido (uno por vez, por grupos). **Refuerzo en código:** `speakable()` quita `* _ # \` > |` y viñetas antes de enviar a TTS. **No hay ningún tope duro de longitud** (ni en tokens ni en frases).

El **brief** (`brief.py`) se habla al inicio, es determinista y empieza con "Soy Lumi…"; sus 3 a 5 preguntas sugeridas se validan contra las tools.

### 1.3 Tools activas (`backend/app/agent/tools.py`)

Siete tools, **sin SQL libre**, argumentos validados con JSON Schema (`additionalProperties: false`); los enums salen del perfil de datos al arrancar. Resultado compacto con `estado`, `valor`, `filtros`, `filas_usadas`, `fecha_corte`, `origen`. Máximo 10 elementos por lista. Límite de **2 llamadas por turno** (`ToolSession`; la tercera devuelve `limite_llamadas`).

| Tool | Parámetros | Qué hace |
|---|---|---|
| `count_ips` | filtros: `departamento`(enum 33), `municipio`, `naturaleza`(enum), `nivel_atencion`(1-3) | `COUNT(DISTINCT codigo_prestador)` |
| `count_sedes` | mismos filtros | `COUNT(DISTINCT sede_id)` |
| `sum_capacidad` | `grupo_capacidad`(enum 7, requerido), `descripcion_capacidad`, filtros | Suma `cantidad_capacidad` |
| `top_n` | `dimension`, `metrica`(ips/sedes/capacidad), `n`, filtros, capacidad | Ranking, máx. 10 |
| `group_by` | igual a `top_n` sin `n` | Hasta 10 grupos (`acotado` si hay más) |
| `listar_ips` | `grupo_capacidad`, `descripcion_capacidad`, filtros, `n` (1-10, defecto 5) | Sedes **de un lugar** con nombre, dirección, teléfono y capacidad; ordena por capacidad |
| `buscar_ips` | `nombre`(2-100), `departamento`, `municipio` | Busca IPS por nombre; **no devuelve contacto** |

### 1.4 Estados y cómo los trata el prompt

| Estado | Cuándo | Instrucción al agente | ¿Respaldada por prueba? |
|---|---|---|---|
| `no_encontrado` | municipio o `descripcion_capacidad` inexistente, con ≤3 sugerencias | Pedir aclaración con una sugerencia; nunca "cero" | Sí (4.11, 4.12b, tests de tools) |
| `sin_resultados` | filtros válidos, 0 filas | Decirlo y sugerir ajustar | Sí |
| `ambiguo` | varios candidatos (descripción o nombre) | Nombrar pocos y preguntar cuál | Sí (4.12) |
| `sin_cobertura` | `nivel_atencion` + naturaleza Privada/Mixta explícita | Explicar que el dato casi no existe | Sí (4.8) |
| `error_validacion` | enum o campo inválido | **Nada en el prompt**; el modelo reintenta (gasta presupuesto de llamadas) | Parcial |
| `limite_llamadas` | 3.ª llamada del turno | Responder con la evidencia disponible (mensaje de la tool) | Sí |

### 1.5 Búsqueda de nombres y lugares

- **Normalización:** `norm()` pasa a minúsculas y quita tildes (NFD), igual que las columnas `*_norm` de DuckDB. Tildes y mayúsculas **no** son un problema.
- **`buscar_ips`, 3 pasos en cascada:** (1) igualdad exacta con `nombre_prestador_norm` o `nombre_sede_norm`; (2) si no hay resultados, **todas** las palabras de la consulta como `LIKE '%palabra%'` (AND) sobre ambos nombres; (3) si sigue vacío, `difflib` con corte 0,9 **solo sobre nombres de prestador**. Resultado de 1 prestador → `ok`; varios → `ambiguo` (máx. 10, orden por longitud del nombre); ninguno → `sin_resultados`.
- **Municipios:** igualdad exacta con `municipio_norm`; si no existe, `difflib` (corte 0,6) devuelve hasta 3 **sugerencias, nunca resuelve solo**.
- **Departamentos y distritos:** el filtro usa `departamento_canonico`, que mapea Cali y Buenaventura a Valle del Cauca, Barranquilla a Atlántico, Cartagena a Bolívar y Santa Marta a Magdalena; Bogotá D.C. queda como está. Con `departamento` filtrado se devuelve `incluye_distritos`.
- **Descripción de capacidad:** exacta, luego coincidencia por raíces de palabras (quita solo la `s` final) con *stopwords*, luego `difflib` 0,9; 1 candidato → resuelve, varios → `ambiguo`, ninguno → `no_encontrado` con 3 sugerencias.

---

## 2. Puntos débiles detectados (priorizados)

Leyenda: **P0** corrige el valor central del producto; **P1** degrada respuestas con frecuencia; **P2** pulido o riesgo menor.

### P0-1. No hay forma de obtener el contacto de **una IPS concreta por nombre**
`buscar_ips` devuelve nombre, naturaleza, departamento, municipio y nº de sedes, pero **ni dirección ni teléfono**. `listar_ips` sí los devuelve, pero **solo filtra por lugar y capacidad, no por nombre**, y ordena por camas. Para "¿cuál es el teléfono del Hospital Pablo Tobón Uribe?" el agente debe: buscar el nombre (sin contacto) → listar el municipio (n ≤ 10, ordenado por camas) y **esperar que esa IPS aparezca entre las 10 primeras**. Si no aparece, el modelo queda sin dato y, bajo presión conversacional, puede improvisar. Es justo la pregunta que el prompt promete responder ("la dirección y el teléfono de cada sede").
Además, `buscar_ips` agrupa por prestador: una IPS con 30 sedes aparece como una fila con `sedes: 30` y **sin listar las sedes**, así que no hay manera de elegir una sede concreta.

### P0-2. El grounding **no está verificado con el modelo de producción**
- La tarea 5.2 de `grounded-agent` sigue abierta: el verificador `ungrounded_numbers` existe, pero `text_agent.py` evalúa contra **OpenAI Chat Completions** (`OPENAI_API_KEY` + `GOLD_AGENT_MODEL`), mientras producción usa **Groq `gpt-oss-120b`** (el crédito de OpenAI se agotó, según `deployment-readme`). Nadie ha medido si ese modelo elige bien las tools ni si inventa cifras.
- **No hay guardia en tiempo de ejecución:** el prompt es la única barrera. Ninguna capa del servidor compara los números hablados con los de los resultados de tool (`ungrounded_numbers` existe pero solo se usa en la evaluación).
- Las pruebas de oro actuales validan **las tools** (15/15 contra SQL), no **la conducta del modelo**.

### P1-3. "IPS en Cali" puede contar todo el Valle del Cauca **[verificar con el modelo]**
La descripción del parámetro `departamento` dice: *"Cali, Cartagena, etc. se cuentan dentro de su departamento"*. Esa frase invita a pasar `departamento="Valle del Cauca"` cuando el usuario dice "Cali", y el resultado sería **813 IPS en lugar de las de Cali** (4.7b: sin distritos son 285 para el Valle "literal"; Cali es un subconjunto). El prompt no explica cuándo usar `municipio` y cuándo `departamento` para esas ciudades. Además `departamento="Cali"` no es un valor del enum → `error_validacion` **sin lista de permitidos** (33 valores > 10, `_compact_error` no los adjunta), y el reintento consume uno de los 2 intentos.

### P1-4. Homónimos de municipio se mezclan sin avisar
`_place()` resuelve a `municipio_norm` **sin considerar el departamento**: `municipio="Santa Rosa"`, `"San Antonio"`, `"La Unión"`, `"Buenavista"`… existen en varios departamentos **[verificar en el snapshot]** y `count_ips`/`listar_ips` los **suman o mezclan** sin devolver `ambiguo`. Solo `group_by` por municipio incluye el departamento en la clave. Riesgo de cifra incorrecta presentada con total seguridad.

### P1-5. Búsqueda de nombres frágil para voz
- **Pasos 1 y 2 exigen que todas las palabras estén:** si Deepgram escribe "Pablo Tobon Uribe" bien, funciona; si omite una palabra, agrega "clínica" donde el dato dice "hospital" o transcribe mal una (p. ej. "Tovón"), el AND falla.
- **El paso 3 (difuso) solo mira nombres de prestador** (no de sede) y exige similitud 0,9: casi no rescata errores de reconocimiento de voz.
- **Sin ranking por relevancia:** los candidatos se ordenan por **longitud del nombre** y se cortan a 50 antes de mostrar 10; consultas genéricas ("clínica santa maría", 4.12) devuelven el subconjunto más corto, no el más probable.
- **`LIKE '%t%'` es por subcadena:** "san" coincide con "Sanitas", "Sanatorio"…; palabras vacías ("de", "la", "ips", "hospital") cuentan como obligatorias. No hay búsqueda por NIT ni `codigo_prestador`.
- **Coste:** el paso 3 carga **todos** los nombres de prestador (~9.320) a Python por consulta y calcula `difflib`; p95 medido 25 ms, aceptable hoy, pero escala mal.

### P1-6. Longitud y legibilidad para TTS: el control es solo por prompt
- **Sin tope duro:** `max_completion_tokens=1024` (con *reasoning* de gpt-oss que **consume ese mismo presupuesto**). Nada impide 6 frases; el "1 a 3 frases" depende de que el modelo obedezca.
- **Instrucciones que chocan:** "una a tres frases" frente a la regla de **emergencias** (123 + 1-2 opciones con dirección y teléfono + advertencia sobre el corte), y frente a `listar_ips` ("dos o tres opciones con su nombre y ofrece más"). La emergencia casi seguro excede 3 frases.
- **Datos que la voz lee mal:** direcciones ("Cra 43 A # 1 Sur 50"), teléfonos, siglas (IPS, ESE, "D.C."), sedes con nombres largos. `speakable()` **no normaliza números ni abreviaturas**; el prompt pide "pausado y por grupos" pero el TTS por frase (Aura-2) no recibe pausas explícitas. **[verificar con audio real]**: cómo lee Aura-2 español "9.320", "45.262" y los teléfonos.
- **Partición por frases:** `SENTENCE_END` corta en `.`, `!`, `?`, `;`, `:`, `…` seguidos de espacio; abreviaturas como "D.C. " o "S.A.S. " parten la frase a mitad. La primera frase se corta a ~60 caracteres en la coma para bajar latencia, lo que puede dar entonación entrecortada.
- **Muletillas fijas** (4 frases rotativas) se repiten en conversaciones largas.

### P1-7. El filtro `nivel_atencion` sin naturaleza calla que solo cuenta públicas
`sin_cobertura` solo se dispara si el usuario **menciona** naturaleza privada/mixta. Con "¿cuántas IPS son de nivel 1?" el resultado es `ok` con el conteo de públicas (4.7 documenta que las de nivel 3 son todas públicas), **sin nota** en el resultado. El modelo podría presentar 853 como "IPS de nivel 1" a secas, sin aclarar que es el subconjunto público.

### P2-8. Memoria de conversación sin los resultados de las tools
`_remember_assistant()` guarda en `history` **solo el texto hablado**; los mensajes `tool` y sus resultados se descartan al terminar el turno. En "¿y la segunda?" o "dame su teléfono" el modelo no tiene los datos de la lista anterior (que sí contenían teléfonos) y debe volver a consultar; si el orden o el filtro cambian, la "segunda" ya no es la misma. Se agrava con P0-1.

### P2-9. Resolución de descripciones de capacidad: sin sinónimos ni morfología
El *stemmer* solo quita la `s` final; "pediátrico/pediátrica", "UCI/cuidado intensivo", "urgencias/emergencias", "camillas de observación" no se relacionan **[verificar con los 41 valores de CAMAS y los de otros grupos]**. Con corte 0,9 el fallback difuso casi no actúa → el usuario recibe `no_encontrado` o `ambiguo` donde un humano entendería.

### P2-10. Rankings truncados en silencio
`group_by departamento` tiene 33 grupos y devuelve 10 con `acotado: true`; el prompt no dice cómo comunicarlo, y "¿cuántas IPS hay por departamento?" se contesta con un fragmento. `top_n` por defecto usa 5.

### P2-11. Desfase entre código, specs y UI
- **`listar_ips` no existe en OpenSpec** (0 menciones). Las specs de `agent-tools` dicen "exactamente seis tools", el código tiene **siete** y el test lo afirma. `agent-grounding` además prohíbe contactos que `listar_ips` entrega siempre.
- La spec exige resultados "sin campos no solicitados como correos o teléfonos"; `listar_ips` incluye dirección y teléfono en **cada** resultado (cuenta contra el prompt "solo si te los piden"). Además `summarize_for_ui` reenvía el resultado completo (con contactos) al navegador en `agent.tool`.
- Los requisitos de `voice-session` siguen redactados solo para OpenAI Realtime; el modo Groq está en `design.md` como "pendiente de formalizar".
- Tareas abiertas relevantes: `grounded-agent` 5.2; `realtime-voice` 4.1, 4.4, 5.2, 7.2, 7.3 (todas requieren claves reales).

### P3. Observaciones menores
- Nombres de departamento con tilde y punto (`Bogotá D.C`): el modelo debe copiar el valor exacto del enum; un municipio dicho como "Bogotá" frente al valor real del dato **[verificar]** puede devolver `no_encontrado` con sugerencia por no ser coincidencia exacta.
- `temperature 0.3` con *reasoning* bajo: razonable; `tool_choice: auto` permite responder sin tool (el prompt manda consultar, no lo fuerza).
- `INSTRUCTIONS_MAX_CHARS` está en 3.400 y el prompt usa 3.235: queda **95 % del presupuesto**, cualquier regla nueva obliga a recortar o subir el límite.

---

## 3. Menú de opciones de mejora

Cada opción es independiente salvo donde se indica. Esfuerzo: **S** (<1 h), **M** (½ día), **L** (≥1 día). Riesgo: efecto colateral sobre lo que ya pasa las pruebas de oro.

### A. Contacto por nombre (P0-1)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **A1** | `buscar_ips` devuelve también `direccion` y `telefono` (por sede) cuando hay **un solo** candidato, y lista sus sedes si son ≤5 | M | Bajo; actualizar spec y test |
| **A2** | Nuevo parámetro `nombre` en `listar_ips` (filtra por `nombre_*_norm`) para listar las sedes de una IPS con contacto | M | Bajo |
| **A3** | Nueva tool `contacto_ips(codigo_prestador, sede?)` que se llama tras elegir el candidato de `buscar_ips`; `buscar_ips` incluye `codigo_prestador` y `sede_id` | M | Medio: más superficie y 2 llamadas por turno (justo el presupuesto) |
| **Recomendada** | **A1 + incluir `sede_id`/`codigo_prestador` en candidatos** para desambiguar y mantener 1-2 llamadas |  |  |

### B. Evaluación y guardias de grounding (P0-2)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **B1** | Adaptar `text_agent.py` para correr contra **Groq** (misma API compatible) y ejecutar las 15 preguntas de oro con `ungrounded_numbers`; guardar el informe | M | Ninguno (solo evaluación) |
| **B2** | Ampliar las preguntas de oro con: contacto por nombre, "IPS en Cali", homónimos, "nivel 1" sin naturaleza, emergencia, pregunta compuesta, ASR con error | M | Ninguno |
| **B3** | Guardia en producción: antes de enviar una frase a TTS, extraer cifras y compararlas con los resultados del turno; si no coinciden, registrar (`log.warning`) y/o reemplazar por "no tengo ese dato" | L | Medio: falsos positivos con redondeos ("unas 45 mil"); empezar solo registrando |
| **Recomendada** | **B1 + B2 primero** (mide antes de tocar prompts); B3 en modo "solo log" |  |  |

### C. Lugares y distritos (P1-3, P1-4, P1-7)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **C1** | Reescribir la descripción de `departamento`/`municipio`: "para una ciudad usa `municipio`; usa `departamento` solo si preguntan por todo el departamento" y añadir al prompt la regla de ciudades distrito (Cali, Cartagena, Barranquilla, Santa Marta, Buenaventura, Bogotá) | S | Bajo |
| **C2** | `_place()` devuelve `ambiguo` con los departamentos candidatos cuando el municipio existe en varios; aceptar `departamento` como desempate | M | Bajo/medio: nuevo estado a documentar |
| **C3** | Añadir `nota` al resultado cuando se filtra `nivel_atencion` sin naturaleza: "solo cuenta IPS públicas" | S | Bajo |
| **C4** | `_compact_error` adjunta `permitidos` también para enums de 33 valores (o las 5 sugerencias más parecidas por `difflib`) | S | Bajo |
| **C5** | Alias de lugares ("Bogotá" → `Bogotá D.C.`, "Cali"…) antes de resolver | S | Bajo |
| **Recomendada** | **C1 + C3 + C4** ya; **C2** si [verificar] confirma homónimos reales |  |  |

### D. Búsqueda difusa de nombres (P1-5)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **D1** | Quitar *stopwords* y palabras genéricas ("hospital", "clínica", "ips", "ese", "de", "la") del AND; exigir las **palabras distintivas** | S | Bajo |
| **D2** | Ranking por relevancia (puntaje por tokens coincidentes + similitud) en vez de orden por longitud | M | Bajo |
| **D3** | Extender el paso difuso a `nombre_sede_norm` y bajar el corte a ~0,8 **solo si hay un ganador claro** (margen sobre el 2.º); si no, `ambiguo` | M | Medio: más falsos positivos; cubrir con pruebas |
| **D4** | Búsqueda por trigramas/fonética (`jaro_winkler` de DuckDB o `rapidfuzz`) para errores de ASR | M-L | Medio: dependencia nueva si es `rapidfuzz` |
| **D5** | Búsqueda por NIT / `codigo_prestador` | S | Ninguno |
| **Recomendada** | **D1 + D2 + D3** |  |  |

### E. Estilo y longitud para voz (P1-6)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **E1** | Reescribir el bloque "Estilo hablado" con límites verificables: "máximo 40 palabras salvo emergencia", "nunca más de 3 opciones", "di los teléfonos de 3 en 3 dígitos separados por comas", "no leas la dirección completa: barrio y calle principal" y aclarar la excepción de emergencias (hasta 5 frases) | S | Bajo; vigilar el 95 % del presupuesto de caracteres |
| **E2** | Normalizador `speakable()` ampliado: miles `9.320` → "9320" o palabras, teléfonos en grupos, `#`→"número", `Cra`→"carrera", `Cl`→"calle", `D.C.`→"Distrito Capital", `IPS`→"I-P-S" | M | Medio: validar con audio de Aura-2 |
| **E3** | Tope duro: bajar `max_completion_tokens` a ~220 para respuestas sin tools y cortar en la última frase completa | S | Medio: puede truncar emergencias; aplicarlo por tipo de turno |
| **E4** | Variar o hacer opcionales las muletillas (más frases, o ninguna si la tool responde rápido) | S | Ninguno |
| **E5** | Pasar los resultados de `listar_ips` como lista corta para voz (sin `prestador`, campos ya redondeados) y dejar el resto para la UI | M | Bajo |
| **Recomendada** | **E1 + E2** y probar con audio real antes de decidir E3 |  |  |

### F. Conversación y memoria (P2-8, P2-9, P2-10)
| Opción | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| **F1** | Conservar en `history` un **resumen compacto de los resultados** del turno (nombres + teléfonos de la lista) como mensaje de sistema/asistente | M | Medio: más tokens por turno |
| **F2** | Tabla de sinónimos de capacidad (UCI ↔ cuidado intensivo, urgencias ↔ emergencias…) y *stemmer* para género (`o/a`) | M | Bajo |
| **F3** | Instrucción de prompt para rankings truncados ("hay más grupos; ¿quieres ver los siguientes?") y `group_by` con `offset` | S/M | Bajo |
| **F4** | Regla de prompt para `error_validacion`: "corrige el argumento con los valores permitidos y reintenta una vez" | S | Bajo |

### G. Orden documental (P2-11)
| Opción | Cambio | Esfuerzo |
|---|---|---|
| **G1** | Actualizar `agent-tools`/`agent-grounding`/`session-brief` para incluir `listar_ips` (siete tools), contactos y reglas de emergencia | S |
| **G2** | Formalizar en `voice-session` el modo Groq (hoy solo en `design.md`) | S |
| **G3** | Decidir si `agent.tool` debe ocultar `direccion`/`telefono` al navegador o mostrarlos como evidencia | S |

---

## 4. Próximos pasos sugeridos

1. **Medir antes de cambiar (B1 + B2).** Correr la evaluación contra Groq con el prompt y las tools actuales y ampliar las preguntas de oro con los casos de la sección 2 (contacto por nombre, Cali, homónimos, nivel sin naturaleza, emergencia). Esto convierte cada **[verificar]** en un dato y fija la línea base.
2. **Cerrar el agujero de contacto (A1).** Es el cambio de mayor valor y de menor riesgo; depende de poder consultar el snapshot, así que va con tests.
3. **Cambios baratos de prompt y esquema (C1, C3, C4, E1).** Una sola pasada sobre `instructions.py` y las descripciones del esquema; revisar el presupuesto de 3.400 caracteres.
4. **Búsqueda de nombres (D1 → D2 → D3)** con casos de prueba de transcripción con errores.
5. **Voz real (E2, E4)** una vez que haya claves: grabar 10 respuestas con Aura-2 y decidir si E3 hace falta. Cubre también las tareas abiertas 4.1/4.4/7.2/7.3 de `realtime-voice`.
6. **Orden documental (G1-G3)** en el mismo PR que A1, para que specs, código y UI coincidan.
7. **Decisión de equipo pendiente:** ¿se acepta mostrar teléfono y dirección al navegador (G3)? ¿el modo Groq es el camino principal, de modo que `text_agent.py` y las specs de voz deban dejar de asumir OpenAI?

> Ninguno de estos pasos se ha ejecutado. Dime qué opciones del menú aprobamos y cuáles descartamos, y las implemento en ese orden.
