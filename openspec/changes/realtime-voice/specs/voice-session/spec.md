## ADDED Requirements

### Requirement: Habilitación de la voz y configuración
El sistema SHALL activar el módulo de voz solo cuando `VOICE_ENABLED` sea `true`, SHALL exigir `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` en ese caso con el mecanismo de configuración validada de `data-ingestion`, y SHALL leer el modelo de `OPENAI_REALTIME_MODEL` y la voz de `REALTIME_VOICE`. El despliegue SHALL fijar `VOICE_ENABLED=true`, y `/health` SHALL informar el estado de la voz (`enabled` o `disabled`).

#### Scenario: Voz habilitada sin clave
- **WHEN** el backend arranca con `VOICE_ENABLED=true` y sin `DEEPGRAM_API_KEY`
- **THEN** el proceso termina con un mensaje que nombra la variable faltante y no imprime valores de configuración

#### Scenario: Voz apagada
- **WHEN** el backend arranca con `VOICE_ENABLED=false`
- **THEN** arranca sin exigir claves de voz, `/health` informa que la voz está apagada y una solicitud `session.start` recibe el error `voice_disabled`

#### Scenario: Valores de modelo y voz
- **WHEN** se inicia una sesión de voz
- **THEN** el relé usa el modelo de `OPENAI_REALTIME_MODEL` y la voz de `REALTIME_VOICE`, cuyo valor provisional es `marin` (a confirmar de oído en español)

### Requirement: Una sesión de voz por conexión
El sistema SHALL permitir una sola sesión de voz por conexión WebSocket, SHALL aplicar el límite de duración definido en la protección del WebSocket público y SHALL liberar las conexiones a OpenAI y Deepgram y los recursos asociados al cerrar la sesión por cualquier causa.

#### Scenario: Segunda sesión en la misma conexión
- **WHEN** el cliente envía `session.start` con una sesión ya activa
- **THEN** el servidor responde con el error `session_already_active` sin afectar la sesión en curso

#### Scenario: Cierre abrupto
- **WHEN** el navegador cierra el WebSocket sin enviar `session.stop`
- **THEN** el servidor cierra las conexiones a OpenAI y Deepgram en 5 s o menos y libera los recursos de la sesión

### Requirement: Protección del WebSocket público
El sistema SHALL validar el encabezado `Origin` del handshake contra `CORS_ORIGINS` y rechazar los orígenes no permitidos, SHALL limitar a 3 las sesiones de voz simultáneas, SHALL limitar las sesiones nuevas por IP (10 por minuto, configurable), SHALL aplicar una duración máxima de sesión de 15 minutos con un aviso a los 13 minutos, SHALL cerrar con el error `session_limit` (con `detail.reason` igual a `concurrent`, `rate` o `duration`) cuando se alcance un límite, y SHALL registrar cada límite alcanzado sin exponer claves ni datos de configuración.

#### Scenario: Origen no permitido
- **WHEN** el handshake llega con un `Origin` que no está en `CORS_ORIGINS`
- **THEN** el servidor rechaza la conexión con HTTP 403 y registra el origen rechazado

#### Scenario: Sesiones simultáneas
- **WHEN** ya hay 3 sesiones de voz activas y llega un `session.start`
- **THEN** el servidor responde con el error `session_limit` y `detail.reason` igual a `concurrent`, sin afectar las sesiones activas

#### Scenario: Sesiones nuevas por IP
- **WHEN** una misma IP supera 10 sesiones nuevas en un minuto
- **THEN** el servidor responde con el error `session_limit` y `detail.reason` igual a `rate`, y el límite se registra

#### Scenario: Aviso previo al fin
- **WHEN** una sesión cumple 13 minutos
- **THEN** el servidor emite un error de severidad `warning` con código `session_expiring` y `detail.seconds_left` igual a 120

#### Scenario: Duración máxima
- **WHEN** una sesión cumple 15 minutos
- **THEN** el servidor emite `session_limit` con `detail.reason` igual a `duration` y la cierra de forma ordenada

#### Scenario: Registro sin secretos
- **WHEN** se registra cualquier límite alcanzado
- **THEN** el registro incluye el tipo de límite y la IP, y no incluye claves ni valores de configuración

### Requirement: Relé hacia OpenAI Realtime
El sistema SHALL abrir por sesión una conexión WebSocket servidor a servidor con OpenAI Realtime, SHALL reenviar el audio del micrófono (PCM16 mono a 24 kHz) y SHALL registrar en la sesión las function tools de `grounded-agent` y las instrucciones de `agent-grounding` sin redefinirlas.

#### Scenario: Audio hacia OpenAI
- **WHEN** el cliente envía un frame binario de audio
- **THEN** el servidor lo reenvía a OpenAI sin transcodificar

#### Scenario: Tools de grounded-agent
- **WHEN** se crea la sesión de OpenAI
- **THEN** se registran las tools de `agent-tools` y las instrucciones de `agent-grounding`

### Requirement: Ejecución de tools en el servidor
El sistema SHALL ejecutar en el servidor cada llamada a una function tool solicitada por el modelo, SHALL devolver el resultado a OpenAI como salida de la función y SHALL NOT exponer SQL, claves ni resultados completos al navegador más allá del resumen del evento `agent.tool`.

#### Scenario: Llamada a una tool
- **WHEN** el modelo solicita `count_ips`
- **THEN** el servidor ejecuta la consulta, devuelve el resultado a OpenAI y emite un evento `agent.tool` con el resumen

#### Scenario: Error en una tool
- **WHEN** una tool falla o excede su límite de llamadas por turno
- **THEN** el servidor devuelve a OpenAI un resultado de error compacto y la sesión continúa

### Requirement: Bifurcación del audio hacia Deepgram
El sistema SHALL enviar el mismo audio del micrófono a Deepgram streaming con el modelo `nova-3`, `language=es` y `diarize=true` mediante una tarea independiente de la ruta de OpenAI, de modo que un retraso o fallo de Deepgram no bloquee la respuesta del agente.

#### Scenario: Audio duplicado
- **WHEN** llega un frame de audio del micrófono
- **THEN** se entrega a OpenAI y a Deepgram sin que la entrega a Deepgram retrase la de OpenAI

#### Scenario: Diarización verificada
- **WHEN** se envía a Deepgram un audio de prueba con dos voces
- **THEN** los resultados distinguen dos hablantes

#### Scenario: Deepgram lento
- **WHEN** Deepgram tarda en responder
- **THEN** la medición de `first_audio_ms` no cambia y la transcripción del usuario aparece cuando Deepgram responde

### Requirement: Latencia del primer audio de respuesta
El sistema SHALL lograr que el primer audio de respuesta llegue al cliente en 1,5 s o menos en el percentil 50 tras terminar el turno del usuario, SHALL medir `first_audio_ms` en el servidor como el tiempo entre el fin de habla detectado por el VAD y el envío del primer frame de audio de respuesta, y SHALL enviar la medición al cliente en el evento `metrics`.

#### Scenario: Pregunta sin tool
- **WHEN** el usuario hace una pregunta que no requiere tools
- **THEN** `first_audio_ms` se mide y se envía en `metrics` con el `turn_id` del turno

#### Scenario: Meta de p50
- **WHEN** se ejecutan las preguntas de oro por voz en el entorno desplegado
- **THEN** la mediana de `first_audio_ms` es 1.500 ms o menos

#### Scenario: Turno con tool
- **WHEN** el turno incluye una llamada a una tool
- **THEN** `metrics` incluye además la duración de la tool y el total del turno

### Requirement: Interrupciones (barge-in)
El sistema SHALL detener al agente cuando el usuario hable mientras responde: cancelar la respuesta en OpenAI, truncar la conversación al punto realmente reproducido según `playback.position`, enviar `audio.clear` al cliente en 300 ms o menos desde la detección de voz (meta inicial, a validar) y marcar el texto del agente como interrumpido.

#### Scenario: Usuario interrumpe
- **WHEN** el usuario habla mientras el agente está en estado `hablando`
- **THEN** el servidor envía `audio.clear`, cancela la respuesta, trunca lo no reproducido y pasa a estado `escuchando`

#### Scenario: Texto tras interrupción
- **WHEN** una respuesta fue interrumpida
- **THEN** el evento final de `agent.text` de ese turno lleva `interrupted` en verdadero y el texto limitado a lo reproducido

#### Scenario: Sin audio viejo
- **WHEN** el cliente recibe `audio.clear`
- **THEN** vacía su cola de audio y descarta los frames del turno cancelado que lleguen después

### Requirement: Detección de turno (VAD) ajustada a español
El sistema SHALL configurar la detección de turno del servidor de OpenAI con parámetros configurables por variables de entorno, SHALL usar `semantic_vad` si el modelo configurado lo soporta y, en caso contrario, `server_vad` con umbral 0,5, relleno previo de 300 ms y silencio de 500 ms, SHALL ajustar esos valores con las preguntas de oro en español y SHALL permitir interrumpir al agente.

#### Scenario: Valores configurables
- **WHEN** se cambian las variables del VAD y se reinicia el backend
- **THEN** la sesión de OpenAI se crea con los nuevos valores

#### Scenario: Valores iniciales de server_vad
- **WHEN** el modelo no soporta `semantic_vad` y no se definen variables del VAD
- **THEN** la sesión usa `server_vad` con umbral 0,5, relleno previo de 300 ms y silencio de 500 ms

#### Scenario: Pausas naturales
- **WHEN** el usuario hace una pausa corta en medio de una frase en español
- **THEN** el turno no se cierra antes de que se cumpla la duración de silencio configurada

### Requirement: Brief como primera respuesta
El sistema SHALL iniciar la sesión emitiendo el brief de `session-brief` como primera respuesta, bajo el turno `t-0000` y sin esperar a que el usuario hable, salvo que `session.start` pida `brief` igual a `skip`.

#### Scenario: Inicio normal
- **WHEN** la sesión pasa a estado `listo`
- **THEN** el agente empieza a hablar el brief y el cliente recibe el evento `session.brief` con `texto` y `preguntas`

#### Scenario: Reconexión sin repetir el brief
- **WHEN** el cliente envía `session.start` con `brief` igual a `skip`
- **THEN** no se habla el brief y la sesión queda en estado `escuchando`

### Requirement: Transcripción de entrada de OpenAI siempre activa
El sistema SHALL habilitar siempre la transcripción de entrada en la sesión de OpenAI con el modelo más barato recomendado por la documentación vigente, configurable mediante `OPENAI_INPUT_TRANSCRIPTION_MODEL`, para disponer del respaldo de texto del usuario sin retraso cuando Deepgram falle.

#### Scenario: Respaldo disponible
- **WHEN** Deepgram falla en mitad de un turno
- **THEN** el texto del usuario de ese turno se obtiene de la transcripción de entrada de OpenAI ya en curso

#### Scenario: Modelo configurable
- **WHEN** se define `OPENAI_INPUT_TRANSCRIPTION_MODEL`
- **THEN** la sesión de OpenAI usa ese modelo para la transcripción de entrada

### Requirement: Degradación si falla Deepgram
El sistema SHALL, si Deepgram falla o se desconecta, usar para el texto visible del usuario la transcripción de entrada de OpenAI sin etiquetas de hablante, SHALL marcar esos eventos como degradados, SHALL avisar a la UI con un error de severidad `warning` en 2 s o menos y SHALL reintentar la conexión a Deepgram en segundo plano.

#### Scenario: Caída de Deepgram
- **WHEN** la conexión a Deepgram se cae durante la sesión
- **THEN** la voz sigue funcionando, los eventos `transcript.*` posteriores llevan `degraded` en verdadero con `speaker` igual a `user` y la UI recibe el aviso

#### Scenario: Recuperación
- **WHEN** Deepgram vuelve a estar disponible
- **THEN** los eventos de transcripción vuelven a su fuente normal con etiquetas de hablante y la UI recibe un `session.state` que lo indica

### Requirement: Degradación si falla OpenAI
El sistema SHALL, si OpenAI falla o se desconecta, enviar un error tipificado con mensaje claro, mantener abierto el WebSocket con el cliente, conservar la transcripción ya emitida y ofrecer reintentar.

#### Scenario: Caída de OpenAI
- **WHEN** la conexión con OpenAI se cae durante un turno
- **THEN** el cliente recibe el error `openai_unavailable` con severidad `fatal` para la voz, el estado pasa a `error` y el WebSocket sigue abierto

#### Scenario: Reintento
- **WHEN** el cliente envía un nuevo `session.start` tras el error
- **THEN** se crea una sesión nueva sin reiniciar el backend

### Requirement: Entrada de texto de respaldo
El sistema SHALL aceptar el mensaje `text.message` como turno del usuario sin pasar por STT, SHALL responder con las mismas tools y reglas y SHALL emitir los eventos de ese turno con el mismo contrato.

#### Scenario: Pregunta por texto
- **WHEN** el cliente envía `text.message` con una pregunta
- **THEN** el servidor emite `transcript.final` del usuario con la fuente `text` y la respuesta del agente en `agent.text` y audio

#### Scenario: Texto sin voz
- **WHEN** `session.start` indica `audio_out` en falso
- **THEN** el agente responde solo con texto y no se envía audio

### Requirement: Prueba de las preguntas de oro por voz
El sistema SHALL contar con una prueba que ejecute las preguntas de oro de `grounded-agent` por voz (o con audio sintético) en unas 20 corridas, SHALL registrar `first_audio_ms` y `vad_silence_ms` de cada turno, SHALL reportar la mediana y el percentil 95 de `first_audio_ms` y la latencia percibida (`vad_silence_ms` + `first_audio_ms`), SHALL fallar si la mediana supera 1.500 ms y SHALL tomar 2.500 ms de percentil 95 como meta orientativa que no hace fallar la prueba.

#### Scenario: Ejecución de la prueba
- **WHEN** se corre la prueba contra el backend desplegado
- **THEN** produce un informe con la latencia de cada pregunta, la mediana y el percentil 95

#### Scenario: Criterio de aceptación
- **WHEN** la mediana de `first_audio_ms` supera 1.500 ms
- **THEN** la prueba se marca como fallida

#### Scenario: Meta orientativa de p95
- **WHEN** el percentil 95 de `first_audio_ms` supera 2.500 ms y la mediana cumple
- **THEN** la prueba pasa y el informe marca el p95 como fuera de la meta orientativa

#### Scenario: Latencia percibida
- **WHEN** el informe reporta un turno
- **THEN** incluye la latencia percibida calculada como `vad_silence_ms` más `first_audio_ms`
