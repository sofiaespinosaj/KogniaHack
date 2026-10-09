## ADDED Requirements

### Requirement: Etiquetas de hablante estables
El sistema SHALL traducir los ids de hablante de Deepgram a `speaker_1`, `speaker_2`, etc., en el orden en que cada id aparece por primera vez en un resultado final, SHALL mantener esa correspondencia durante toda la sesión y SHALL usar siempre `agent` para el agente. Los ids de Deepgram SHALL NOT exponerse al cliente. Los eventos SHALL ser los de `ws-event-contract` sin campos nuevos.

#### Scenario: Primer hablante
- **WHEN** el primer enunciado final de la sesión llega con el id 0 de Deepgram
- **THEN** el `transcript.final` lleva `speaker` igual a `speaker_1`

#### Scenario: Orden de aparición
- **WHEN** el primer enunciado final llega con el id 1 de Deepgram y el siguiente con el id 0
- **THEN** el id 1 es `speaker_1` y el id 0 es `speaker_2`

#### Scenario: Estabilidad en la sesión
- **WHEN** un hablante ya etiquetado vuelve a hablar varios turnos después
- **THEN** recibe la misma etiqueta que tuvo la primera vez

#### Scenario: Agente
- **WHEN** se muestra el texto del agente
- **THEN** su hablante es `agent` y nunca recibe una etiqueta `speaker_N`

### Requirement: Estabilización de etiquetas en parciales
El sistema SHALL tratar como provisional el hablante de `transcript.partial`, SHALL fijar el hablante definitivo en `transcript.final` y SHALL NOT cambiarlo después. Una parcial SHALL NOT introducir una etiqueta nueva. Dentro de un resultado final, una racha de otro hablante más corta que la duración mínima configurada SHALL unirse al hablante vecino.

#### Scenario: Sin parpadeo
- **WHEN** Deepgram alterna el id de hablante entre parciales del mismo enunciado
- **THEN** las parciales mantienen la etiqueta del enunciado en curso y solo el final puede fijar otra

#### Scenario: Hablante nuevo
- **WHEN** aparece un id de Deepgram nunca visto
- **THEN** su etiqueta nueva aparece por primera vez en un `transcript.final`

#### Scenario: Racha corta
- **WHEN** un resultado final contiene una racha de otro hablante más corta que la duración mínima
- **THEN** esa racha se une al enunciado del hablante vecino y no abre un enunciado nuevo

#### Scenario: Final inmutable
- **WHEN** ya se emitió el `transcript.final` de un enunciado
- **THEN** ningún evento posterior cambia su `speaker`

### Requirement: Anti-eco del agente
El sistema SHALL NOT etiquetar como humano un segmento de Deepgram que se solape en el tiempo con el audio del agente y cuyo texto coincida con lo que el agente está diciendo según los umbrales configurados. Esos segmentos SHALL descartarse sin consumir una etiqueta de hablante y SHALL registrarse sin su texto.

#### Scenario: Eco del altavoz
- **WHEN** el micrófono capta al agente y Deepgram devuelve un segmento con el mismo texto durante su audio
- **THEN** no se emite `transcript.final` humano para ese segmento ni se crea una etiqueta nueva

#### Scenario: Interrupción real
- **WHEN** el usuario habla encima del agente con palabras distintas
- **THEN** su enunciado se emite con su etiqueta de hablante

#### Scenario: Registro de descartes
- **WHEN** se descarta un segmento como eco
- **THEN** el registro indica el descarte, el `turn_id` y la duración, sin el texto

### Requirement: Marcas de tiempo coherentes
El sistema SHALL expresar `ts` y `ts_end` en milisegundos desde el inicio de la sesión, SHALL tomar `ts` del inicio de la primera palabra y `ts_end` del final de la última, SHALL garantizar `ts` menor o igual que `ts_end` y SHALL mantener la coherencia tras una reconexión con Deepgram.

#### Scenario: Orden temporal
- **WHEN** se emiten dos enunciados finales consecutivos
- **THEN** el `ts` del segundo es mayor o igual que el `ts` del primero

#### Scenario: Reloj de la sesión
- **WHEN** un enunciado empieza 7 s después del inicio de la sesión
- **THEN** su `ts` está cerca de 7.000 dentro de la tolerancia configurada (TBD, inicial 300 ms)

#### Scenario: Reconexión con Deepgram
- **WHEN** la conexión con Deepgram se recupera tras una caída
- **THEN** los `ts` posteriores siguen contando desde el inicio de la sesión y no vuelven a cero

### Requirement: Formato, parciales y fin de enunciado
El sistema SHALL pedir a Deepgram resultados parciales, puntuación y formato inteligente en español, SHALL emitir `transcript.partial` mientras el usuario habla y SHALL emitir `transcript.final` al fin de enunciado que marque Deepgram.

#### Scenario: Puntuación
- **WHEN** el usuario hace una pregunta
- **THEN** el texto final incluye mayúscula inicial y signos de interrogación

#### Scenario: Parciales durante el habla
- **WHEN** el usuario habla durante más de un segundo
- **THEN** el cliente recibe al menos un `transcript.partial` antes del `transcript.final` con el mismo `utt_id`

#### Scenario: Fin de enunciado
- **WHEN** el usuario hace una pausa mayor que el umbral de fin de enunciado
- **THEN** se emite el `transcript.final` de ese enunciado

### Requirement: Vocabulario del dominio
El sistema SHALL enviar a Deepgram una lista de términos clave del dominio para mejorar la precisión: siglas (IPS, REPS, ESE), los grupos de capacidad del dataset y los nombres de departamentos y distritos tomados de los datos cargados, respetando el límite de términos de Deepgram.

#### Scenario: Siglas
- **WHEN** el usuario dice «REPS» o «IPS»
- **THEN** la transcripción final escribe la sigla en mayúsculas

#### Scenario: Nombres del dataset
- **WHEN** el usuario nombra un departamento como «Norte de Santander» o «Guainía»
- **THEN** el término está en la lista enviada a Deepgram

#### Scenario: Límite de términos
- **WHEN** la lista supera el límite configurado
- **THEN** se envían primero las siglas y los grupos de capacidad, luego los departamentos, y el exceso se registra

### Requirement: Verificación de la diarización
El sistema SHALL contar con un audio corto de dos voces con su transcripción y hablante esperados, y con una prueba que produzca un informe con el porcentaje de enunciados con hablante correcto y el error de transcripción en las preguntas de oro. La prueba SHALL fallar si menos del 90 % de los enunciados tiene el hablante correcto.

#### Scenario: Dos voces
- **WHEN** se procesa el audio de prueba de dos voces
- **THEN** se distinguen dos etiquetas y al menos el 90 % de los enunciados tiene el hablante correcto

#### Scenario: Preguntas de oro
- **WHEN** se procesan las preguntas de oro
- **THEN** el informe registra el WER de cada una y lo compara con la meta configurada (TBD)

#### Scenario: Informe
- **WHEN** termina la prueba
- **THEN** se guarda un informe con los resultados por enunciado, los totales y la fecha de la corrida
