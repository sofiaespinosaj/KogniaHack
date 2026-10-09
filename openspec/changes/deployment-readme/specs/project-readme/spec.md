## ADDED Requirements

### Requirement: README de una página
El repositorio SHALL tener en la raíz un `README.md` de una página que incluya: qué hace el agente, las URLs públicas, el stack, un diagrama de arquitectura, las decisiones técnicas principales con su porqué, cómo ejecutar en local y cómo correr las pruebas.

#### Scenario: Lectura del jurado
- **WHEN** el jurado abre el repositorio
- **THEN** encuentra en el README la URL pública, el stack, la arquitectura y las decisiones sin tener que abrir otros archivos

#### Scenario: Ejecución local
- **WHEN** alguien sigue las instrucciones del README
- **THEN** puede levantar el backend y el frontend en local con los comandos indicados

### Requirement: Declaración de uso de IA
El README SHALL declarar qué partes del proyecto se generaron o se asistieron con IA (código, especificaciones, textos, audio sintético de prueba) y con qué herramientas, y qué revisó o decidió el equipo.

#### Scenario: Declaración presente
- **WHEN** se lee la sección de uso de IA
- **THEN** se nombran las herramientas usadas y las partes generadas o asistidas, incluido el audio sintético de las preguntas de oro

### Requirement: Limitaciones conocidas
El README SHALL listar las limitaciones conocidas: que el agente solo responde con datos del dataset y su fecha de corte, que el sentimiento se infiere solo del texto, y que la diarización depende de Deepgram y se degrada a transcripción sin etiquetas.

#### Scenario: Limitaciones visibles
- **WHEN** se lee el README
- **THEN** las limitaciones aparecen en una sección propia
