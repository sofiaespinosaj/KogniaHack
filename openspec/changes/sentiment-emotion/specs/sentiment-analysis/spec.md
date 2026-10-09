## ADDED Requirements

### Requirement: Análisis asíncrono por enunciado humano
El sistema SHALL analizar el sentimiento y la emoción de cada `transcript.final` cuyo `speaker` sea humano (`speaker_N` o `user`, de cualquier `source`), SHALL hacerlo de forma asíncrona fuera de la ruta de voz y SHALL emitir el resultado con el evento `sentiment` de `ws-event-contract` sin redefinirlo. El texto del agente SHALL NOT analizarse.

#### Scenario: Enunciado de un hablante
- **WHEN** se emite un `transcript.final` con `speaker` igual a `speaker_1`
- **THEN** después se emite un `sentiment` con el mismo `turn_id`, `utt_id` y `speaker`

#### Scenario: Pregunta escrita
- **WHEN** el usuario envía un `text.message`
- **THEN** su `transcript.final` con `source` igual a `text` también recibe un `sentiment`

#### Scenario: Agente
- **WHEN** el agente responde
- **THEN** no se emite `sentiment` para su texto

#### Scenario: Sin bloqueo
- **WHEN** el análisis de un enunciado está en curso
- **THEN** el audio y los eventos del agente se emiten sin esperar al análisis

### Requirement: Modelo y salida validada
El sistema SHALL usar un modelo de texto pequeño de OpenAI configurable con `OPENAI_SENTIMENT_MODEL`, SHALL pedir una salida JSON restringida por esquema y SHALL validar el resultado contra ese esquema antes de emitirlo; un resultado que no cumpla el esquema SHALL descartarse.

#### Scenario: Modelo configurable
- **WHEN** se define `OPENAI_SENTIMENT_MODEL`
- **THEN** el análisis usa ese modelo

#### Scenario: Salida inválida
- **WHEN** el modelo devuelve un valor fuera de la lista o un JSON mal formado
- **THEN** no se emite `sentiment` para ese enunciado y el fallo se registra

### Requirement: Contexto de la conversación
El sistema SHALL enviar al modelo, además del enunciado a clasificar, los dos enunciados humanos anteriores de la misma sesión con su hablante, indicando cuál se clasifica. El contexto SHALL NOT incluir datos de otras sesiones.

#### Scenario: Respuesta corta con contexto
- **WHEN** el usuario dice «no, eso no era lo que pregunté» tras una pregunta anterior
- **THEN** el modelo recibe la pregunta anterior como contexto y solo clasifica el enunciado actual

#### Scenario: Inicio de sesión
- **WHEN** se analiza el primer enunciado de la sesión
- **THEN** se clasifica sin contexto previo

### Requirement: Valores permitidos
El sistema SHALL emitir `sentiment` con uno de `positivo`, `neutro` o `negativo`, `emotion` con uno de `interés`, `curiosidad`, `confusión`, `frustración`, `sorpresa`, `enojo`, `alegría` o `neutralidad`, y `score` entre -1 y 1 con signo coherente: mayor que 0 para `positivo`, menor que 0 para `negativo` y cercano a 0 para `neutro` (rango TBD).

#### Scenario: Valores en la lista
- **WHEN** se emite cualquier evento `sentiment`
- **THEN** sus valores de `sentiment` y `emotion` están en las listas cerradas y `score` está entre -1 y 1

#### Scenario: Score incoherente
- **WHEN** el modelo devuelve `negativo` con un `score` positivo
- **THEN** el `score` emitido se ajusta al rango del sentimiento negativo

### Requirement: Enunciados muy cortos
El sistema SHALL resolver sin llamar al modelo los enunciados muy cortos (menos de 3 palabras, TBD) o formados solo por muletillas, emitiendo `sentiment` igual a `neutro`, `emotion` igual a `neutralidad` y `score` igual a 0.

#### Scenario: Muletilla
- **WHEN** el `transcript.final` es «ajá»
- **THEN** se emite `neutro`, `neutralidad` y 0 sin llamada al modelo

### Requirement: Tiempo máximo y fallo silencioso
El sistema SHALL abandonar un análisis que tarde más de 3 s y SHALL fallar en silencio ante timeout, error de red, cuota agotada o respuesta inválida: sin evento `sentiment`, sin evento `error` al cliente y sin afectar la voz ni la UI. Cada fallo SHALL registrarse con su tipo, sin texto del usuario ni claves.

#### Scenario: Timeout
- **WHEN** el modelo no responde en 3 s
- **THEN** no se emite `sentiment` para ese enunciado y la sesión continúa normal

#### Scenario: OpenAI caído
- **WHEN** la API de texto de OpenAI no está disponible
- **THEN** la voz sigue funcionando y el cliente no recibe errores por el análisis

### Requirement: Concurrencia limitada
El sistema SHALL limitar los análisis simultáneos por sesión y por proceso (límites TBD, iniciales 2 y 6) y, al superarlos, SHALL descartar el análisis pendiente más antiguo.

#### Scenario: Ráfaga de enunciados
- **WHEN** llegan más enunciados finales que el límite por sesión mientras hay análisis en curso
- **THEN** nunca hay más análisis en curso que el límite y se descarta el pendiente más antiguo

### Requirement: Latencia del análisis
El sistema SHALL buscar que el `sentiment` se emita 2 s o menos (p50) después del `transcript.final` correspondiente, SHALL medir esa latencia en el servidor por enunciado y SHALL registrarla.

#### Scenario: Medición
- **WHEN** se emite un `sentiment`
- **THEN** el registro incluye el tiempo desde su `transcript.final`

#### Scenario: Meta de p50
- **WHEN** se ejecuta la evaluación con el modelo real
- **THEN** el informe reporta el p50 de latencia y lo compara con la meta de 2 s

### Requirement: Limitación declarada
El sistema SHALL declarar en la documentación y en la UI que el análisis se basa solo en el texto transcrito, sin prosodia ni tono de voz.

#### Scenario: Documentación
- **WHEN** se lee el README del proyecto o el panel de Live Insights
- **THEN** se indica que el sentimiento se infiere solo del texto

### Requirement: Evaluación con frases etiquetadas
El sistema SHALL contar con unas 10 frases en español etiquetadas a mano con su sentimiento y emoción esperados, y con un script que las clasifique con el modelo configurado y genere un informe de aciertos por campo y de latencia.

#### Scenario: Informe de evaluación
- **WHEN** se ejecuta el script de evaluación
- **THEN** el informe muestra, por frase, lo esperado frente a lo obtenido, el total de aciertos de `sentiment` y de `emotion` y la latencia p50
