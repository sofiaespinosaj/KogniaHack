## ADDED Requirements

### Requirement: Respuestas solo con evidencia de tools
El agente SHALL responder únicamente con datos obtenidos de los resultados de sus tools, SHALL indicar de qué consulta sale cada dato y SHALL NOT usar conocimiento propio para dar cifras, nombres o hechos sobre IPS.

#### Scenario: Pregunta respondible
- **WHEN** el usuario pregunta cuántas IPS hay en Antioquia
- **THEN** el agente invoca una tool y responde con la cifra devuelta, mencionando que proviene del dataset

#### Scenario: Cifra no devuelta por una tool
- **WHEN** el modelo no tiene un resultado de tool que respalde una cifra
- **THEN** el agente no la afirma y consulta la tool correspondiente o dice que no tiene el dato

### Requirement: Honestidad ante lo que está fuera de la fuente
El agente SHALL decir con naturalidad que no tiene evidencia cuando la pregunta esté fuera de la fuente o la tool no devuelva resultados, y SHALL ofrecer ejemplos de lo que sí puede responder.

#### Scenario: Pregunta fuera de la fuente
- **WHEN** el usuario pregunta por la calidad médica o las tarifas de una IPS
- **THEN** el agente dice que el dataset no contiene esa información y ofrece alternativas como conteos por zona o capacidad instalada

#### Scenario: Sin resultados
- **WHEN** una tool devuelve `sin_resultados`
- **THEN** el agente lo comunica sin inventar y sugiere ajustar el filtro

#### Scenario: Lugar no encontrado
- **WHEN** una tool devuelve `no_encontrado` con sugerencias
- **THEN** el agente dice que no encuentra ese lugar y pregunta por una de las sugerencias, sin decir que hay cero IPS

### Requirement: Nivel de atención de IPS privadas o mixtas
El agente SHALL explicar que el dataset casi no registra el nivel de atención para IPS privadas o mixtas, porque prácticamente solo existe para las públicas, y SHALL NOT responder "cero" ni inferir un nivel.

#### Scenario: Pregunta sobre nivel de una IPS privada
- **WHEN** el usuario pregunta cuántas IPS privadas son de nivel 2
- **THEN** el agente responde que el dato casi no está registrado para privadas y ofrece el conteo por nivel de las públicas

#### Scenario: Nivel en IPS públicas
- **WHEN** el usuario pregunta cuántas IPS públicas son de nivel 3
- **THEN** el agente responde con la cifra devuelta por la tool

### Requirement: Cita de la fecha de corte
El agente SHALL citar la fecha de corte (5 de noviembre de 2022) al dar cifras y SHALL NOT repetirla en cada frase de una misma respuesta ni en turnos consecutivos que la mencionen ya.

#### Scenario: Primera cifra de la conversación
- **WHEN** el agente da su primera cifra
- **THEN** menciona que los datos corresponden al corte del 5 de noviembre de 2022

#### Scenario: Cifras seguidas
- **WHEN** el agente da varias cifras en el mismo turno
- **THEN** menciona la fecha de corte una sola vez

### Requirement: Conteo por prestadores distintos
El agente SHALL contar IPS como prestadores distintos mediante `count_ips` y SHALL NOT usar el número de filas como número de IPS; las sedes se cuentan con `count_sedes`.

#### Scenario: Cuántas IPS
- **WHEN** el usuario pregunta cuántas IPS existen en total
- **THEN** el agente responde con 9.320 (redondeado al hablar) y no con las 41.427 filas

#### Scenario: Diferencia entre IPS y sedes
- **WHEN** el usuario pregunta por sedes
- **THEN** el agente usa `count_sedes` y no presenta el resultado como número de IPS

### Requirement: Estilo hablado
El agente SHALL responder en 1 a 3 frases, redondear las cifras con precisión razonable, y SHALL NOT leer correos, teléfonos ni direcciones completas de corrido.

#### Scenario: Cifra extensa
- **WHEN** el valor es 45.262
- **THEN** el agente lo dice de forma natural (por ejemplo, "unas 45 mil") sin perder el orden de magnitud

#### Scenario: Lista larga
- **WHEN** el resultado trae 10 elementos
- **THEN** el agente menciona los principales y ofrece el resto, sin enumerarlos todos

#### Scenario: Longitud
- **WHEN** el agente responde cualquier pregunta
- **THEN** la respuesta tiene entre 1 y 3 frases

### Requirement: Datos de contacto solo si se piden
El agente SHALL NOT mencionar gerente, correo, teléfono ni dirección salvo que el usuario los pregunte, y al darlos SHALL ofrecer un dato por vez en lugar de leerlos de corrido.

#### Scenario: Sin pedido de contacto
- **WHEN** el usuario pregunta por la ubicación general de una IPS
- **THEN** el agente responde con departamento y municipio sin dar teléfono ni correo

#### Scenario: Pedido de contacto
- **WHEN** el usuario pregunta por el teléfono de una IPS
- **THEN** el agente da el teléfono, pausado y por grupos, sin añadir otros datos de contacto

### Requirement: Instrucciones de sesión concisas
El sistema SHALL escribir las reglas de grounding, estilo hablado y honestidad como instrucciones de sesión breves y SHALL NOT incluir datos del dataset en ellas, de modo que las cifras provengan solo de tools y del brief.

#### Scenario: Instrucciones sin datos
- **WHEN** se inspecciona el texto de las instrucciones de sesión
- **THEN** no contiene cifras del dataset y su longitud no supera el presupuesto fijado (TBD, a calibrar con pruebas de latencia)
