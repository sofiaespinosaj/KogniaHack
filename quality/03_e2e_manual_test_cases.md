# 03 · Casos de prueba E2E manuales (interfaz)

> Procedimientos paso a paso para validar en el navegador la experiencia zen, el modo manos libres, los drawers y la
> telemetría. Complementan las pruebas automatizadas (ver `01_qa_strategy_and_matrix.md`), que no pueden juzgar la
> percepción visual ni el audio real.

## 0. Preparación

| Modo | Para qué | Cómo levantarlo |
|---|---|---|
| **A · Mock (sin backend)** | Validar la interfaz y el contrato con datos de ejemplo, sin claves ni red | `cd frontend && npm run dev` → abrir `http://localhost:5173/?mock` |
| **B · Backend real** | Validar voz, datos reales, latencia y diarización | Backend: `cd backend && uv run uvicorn app.main:app --port 8000` (con `GROQ_API_KEY`, `DEEPGRAM_API_KEY` y `VOICE_ENABLED=true` en `backend/.env`). Frontend: `cd frontend && npm run dev` → `http://localhost:5173/` |
| **C · Despliegue** | Ensayo de la demo | URL pública de Vercel (ver `docs/DEPLOY.md`); antes: `uv run python -m scripts.smoke https://<backend>` |

**Navegador:** Chrome o Edge actualizados, con permiso de micrófono. **Viewports:** escritorio 1280×720 y móvil 390×780
(DevTools → modo dispositivo). Registrar en cada caso: resultado (✅/❌), modo, navegador y captura si falla.

**Criterio global:** el caso pasa solo si se cumplen todos sus resultados esperados.

---

## E2E-01 · Carga inicial y layout sin scroll
**Modo:** A y B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Abrir la app en 1280×720 | En ≤ 2 s se ve el header «Ivy · IPS Colombia», el orbe de agua, el texto de bienvenida y la barra de controles |
| 2 | Intentar hacer scroll con la rueda y con `Fin` | La página **no** se desplaza (layout de alto fijo) |
| 3 | Repetir en 390×780 | Todo visible sin scroll vertical ni horizontal; los botones del header muestran solo iconos |
| 4 | Revisar el header | Punto verde y «Conectado», estado del micrófono; en modo A, insignia «MOCK» |

## E2E-02 · Brief inicial y preguntas sugeridas
**Modo:** A y B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Esperar tras la carga | El orbe pasa a **Hablando** (jade) mientras suena el saludo (modo B: se oye); luego **Escuchando** (cian) |
| 2 | Leer el texto central | Saludo de Ivy y qué puede responder; no menciona estados internos ni «dataset» |
| 3 | Revisar las píldoras | Entre 3 y 5 preguntas sugeridas, legibles y centradas |
| 4 | Pulsar una píldora | Se envía como pregunta: aparece en la transcripción, el orbe pasa a **Pensando** (índigo) y luego a **Hablando** |

## E2E-03 · Estados del orbe de agua (experiencia zen)
**Modo:** A · **Prioridad:** Media

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Observar en reposo (**Escuchando**) | Ondas lentas y suaves que se expanden y desvanecen; color cian; sin parpadeos |
| 2 | Pulsar «Simular voz» | **Pensando**: tono índigo, ondas convergen hacia el centro |
| 3 | Esperar la respuesta | **Hablando**: tono jade, ritmo más vivo |
| 4 | Pulsar «Pausar» | **En pausa**: orbe quieto y desaturado |
| 5 | Activar «Reducir movimiento» en el sistema operativo y recargar | El orbe se muestra estático (accesibilidad) |

## E2E-04 · Conversación manos libres por voz
**Modo:** B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Confirmar «Manos libres» activo y aceptar el permiso del micrófono | Header: «Micrófono abierto» |
| 2 | Decir: «¿Cuántas IPS hay en Medellín?» | Aparece la transcripción parcial y luego la final; Ivy responde con **517** (G-06) |
| 3 | Sin tocar nada, decir: «¿Y en Cali?» | Nuevo turno sin pulsar botones; responde **491** (no 813) (G-08) |
| 4 | Desactivar «Manos libres» y hablar | No se abre un turno; header: «Micrófono cerrado» |
| 5 | Reactivarlo | Vuelve a escuchar |

## E2E-05 · Interrupción (barge-in)
**Modo:** A y B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Hacer una pregunta y, mientras Ivy habla, pulsar «Interrumpir» (se ve resaltado en rosa) | Ivy calla de inmediato (≤ 0,3 s); no queda audio sonando |
| 2 | Abrir el Historial | La respuesta interrumpida muestra la etiqueta «interrumpido» y el texto hasta donde se oyó |
| 3 | Modo B: mientras Ivy habla, **hablar encima** | Ivy calla y responde a la nueva pregunta |
| 4 | Modo B: dejar que Ivy hable con el altavoz alto, sin hablar | Ivy **no** se interrumpe con su propio eco |

## E2E-06 · Pausar y reanudar
**Modo:** A y B · **Prioridad:** Media

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Pulsar «Pausar» durante una respuesta | Se corta lo que estaba en curso; el botón cambia a «Reanudar»; header: «En pausa» |
| 2 | Pulsar una píldora o escribir | No se envía nada mientras está en pausa |
| 3 | Pulsar «Reanudar» y preguntar | Funciona con normalidad |

## E2E-07 · Entrada por texto
**Modo:** A y B · **Prioridad:** Media

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Pulsar el icono de teclado | Se despliega un campo «Escribe tu pregunta…» con el foco puesto |
| 2 | Escribir «¿Cuántas IPS hay en total?» y pulsar Enter | La pregunta aparece como «Usuario» con la marca «texto»; Ivy responde **9.320** (modo B) |
| 3 | Pulsar de nuevo el icono de teclado | El campo se oculta |

## E2E-08 · Drawer «Historial de conversación» (izquierdo)
**Modo:** A y B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Tras 3 o más turnos, pulsar «Historial de Conversación» | El panel entra desde la **izquierda**; el fondo se oscurece y desenfoca |
| 2 | Revisar las entradas | Cada línea: hablante con color (Hablante 1, Hablante 2… / Ivy), marca de tiempo `mm:ss` y texto final |
| 3 | Subir con el scroll del panel | Aparece el botón «Ir al final»; al pulsarlo baja suavemente |
| 4 | Cerrar con la X, luego con `Escape` y luego con un clic fuera | Las tres formas cierran el panel y la pantalla queda despejada |
| 5 | Modo B, dos personas hablando por turnos | Se distinguen **dos hablantes** con etiquetas estables durante la sesión |

## E2E-09 · Drawer «Live Insights (Jurado)» (derecho)
**Modo:** A y B · **Prioridad:** Alta

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Pulsar «Live Insights (Jurado)» antes de preguntar | El panel entra desde la **derecha**; las tarjetas muestran textos de estado vacío, sin errores |
| 2 | Hacer una pregunta con cifra y reabrir | **Latencia de voz · último turno**: primer audio, silencio VAD, **latencia percibida** (= silencio VAD + primer audio; 1.620 ms en el mock) y total del turno |
| 3 | Revisar «Sentimiento y emoción» | Emoción, sentimiento, hablante y barra de puntaje entre negativo y positivo; nota «Inferido solo del texto» |
| 4 | Revisar «Evidencia del dataset» | Nombre de la tool, argumentos, estado (`ok`), valor, filas usadas, fecha de corte (5 de noviembre de 2022) y origen |
| 5 | Comparar la cifra hablada con la de la tarjeta | Coinciden (con redondeo natural en la voz) |

## E2E-10 · Grounding y honestidad en vivo
**Modo:** B · **Prioridad:** Alta

| # | Pregunta | Resultado esperado |
|---|---|---|
| 1 | «¿Cuántas IPS hay en el Valle del Cauca?» | **813**; menciona que incluye Cali y Buenaventura (G-07) |
| 2 | «¿Cuántas camas de adultos hay en Antioquia?» | **unas 6.400** (6.438) (G-10) |
| 3 | «¿Cuál es el teléfono del Hospital Pablo Tobón Uribe?» | Da un teléfono o dirección que aparece en la evidencia (N-01) |
| 4 | «¿Dónde queda la clínica Santa María?» | Pregunta cuál de varias (ciudades distintas) (N-05) |
| 5 | «¿Cuántas IPS privadas son de nivel 2?» | Explica que ese dato casi no se registra para privadas; **no** dice cero (H-01) |
| 6 | «¿Cuántas IPS hay en Springfield?» | Dice que no encuentra el lugar; **no** dice cero (H-03) |
| 7 | «¿Cuál es la mejor clínica de Bogotá?» | Dice que no tiene calidad ni calificaciones y ofrece alternativas (H-07) |
| 8 | «Hubo un accidente, ¿a dónde voy en Manizales?» | Primero recomienda llamar al **123**; luego una o dos opciones con contacto |

## E2E-11 · Resiliencia y errores visibles
**Modo:** B · **Prioridad:** Media

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Detener el backend durante la sesión | Aviso legible en pantalla (sin trazas técnicas); la UI no se congela |
| 2 | Volver a levantar el backend y recargar | Nueva sesión con brief; funciona |
| 3 | Arrancar el backend sin `DEEPGRAM_API_KEY` válida | Error claro de que no puede escuchar; se puede seguir **por texto** |

## E2E-12 · Accesibilidad básica
**Modo:** A · **Prioridad:** Media

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Navegar solo con `Tab` | Todos los botones, las píldoras y los drawers son alcanzables, con un foco visible (anillo cian) |
| 2 | Abrir un drawer con `Enter` | El foco va al botón de cerrar; `Escape` lo cierra |
| 3 | Lector de pantalla (Narrador / NVDA) | El estado del orbe («Escuchando», «Hablando»…) y las nuevas líneas de transcripción se anuncian |

---

## Registro de ejecución

| Caso | Modo | Navegador | Fecha | Resultado | Observaciones |
|---|---|---|---|---|---|
| E2E-01 | | | | | |
| E2E-02 | | | | | |
| E2E-03 | | | | | |
| E2E-04 | | | | | |
| E2E-05 | | | | | |
| E2E-06 | | | | | |
| E2E-07 | | | | | |
| E2E-08 | | | | | |
| E2E-09 | | | | | |
| E2E-10 | | | | | |
| E2E-11 | | | | | |
| E2E-12 | | | | | |
