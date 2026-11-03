# Skill especializado de revisión de consentimientos para un PIMS

Trabajo de Investigación Formativa del curso Auditoría de Sistemas. Segundo entregable. Universidad Nacional de San Agustín de Arequipa, Escuela Profesional de Ingeniería de Sistemas. Docente: Zárate Carlos. Arequipa, 2026.

Integrantes: Bedregal Pérez, Daniel; Choquecondo Aspilcueta, Daniela; Payehuanca Riquelme, Jhastyn.

## Propósito y alcance de esta entrega

Se presenta `consent-audit`, un skill que convierte la solicitud de revisar un consentimiento en un procedimiento reutilizable de revisión documental. El asistente `consent-supervisor` lo activa dentro de OpenCode, ejecuta las herramientas disponibles y presenta un registro trazable para apoyar al auditor de un sistema de gestión de privacidad de la información, PIMS.

El resultado de esta etapa es un skill funcional especializado, acompañado de la identidad, instrucciones y conocimiento del asistente. Se comprueban su descubrimiento, activación, ejecución y salida. El diseño e integración del proyecto agéntico, la coordinación con otros agentes y una automatización más amplia se desarrollarán en la tercera unidad.

El prototipo revisa criterios parciales sobre consentimiento. Sus resultados son dictámenes documentales provisionales; las decisiones sobre excepciones e información insuficiente requieren revisión humana. El sistema no acredita la conformidad integral de una organización con el PIMS, la ISO o la legislación.

## Problema que atiende dentro del PIMS

Al revisar formularios y avisos de privacidad, el auditor necesita localizar la finalidad, identificar al responsable y los destinatarios, comprobar cómo se obtiene y registra el consentimiento, y examinar cómo puede retirarse. Una respuesta aislada de un asistente puede omitir pasos o variar su formato. El skill organiza esa tarea, establece entradas y herramientas y conserva la relación entre evidencia, criterio, hallazgo y resultado.

El apoyo al PIMS consiste en ordenar la revisión y conservar sus evidencias. El auditor sigue siendo responsable de verificar la suficiencia de los documentos y la aplicabilidad del fundamento normativo.

## De una solicitud a un proceso reutilizable

Como punto de partida explicativo se usa el siguiente prompt de referencia:

> Revisa el formulario de consentimiento, identifica posibles incumplimientos e indica cómo corregirlos.

Este prompt de referencia ilustra la transformación; no se presenta como una reconstrucción de una conversación histórica. Para hacerlo reutilizable se definen los siguientes elementos:

| Elemento del proceso | Definición en el skill |
|---|---|
| Objetivo | Revisar evidencia documental del ciclo de consentimiento |
| Activación | Solicitudes sobre formularios, avisos, registros o mecanismos de revocación |
| Entrada | Documento concreto en texto, con empresa y alcance cuando estén disponibles |
| Conocimiento | Corpus resumido, reglas documentales y catálogo parcial de excepciones |
| Ejecución | Herramienta MCP de auditoría completa o alternativa de consola local |
| Control de calidad | Evidencia con contenido, citas verificables, contexto y revisión de incertidumbre |
| Salida | Registro JSON exacto, informe Markdown y resumen del estado |
| Reutilización | El mismo procedimiento se aplica a distintos archivos sin reescribir las instrucciones |

La especialización está en las decisiones sobre el ciclo de consentimiento y su trazabilidad. La capacidad general de conversar o ejecutar comandos la proporciona OpenCode y su modelo; el skill indica cuándo y cómo utilizarla para esta tarea.

## Activación y estructura del skill

El archivo principal está en `.opencode/skills/consent-audit/SKILL.md`. Su cabecera contiene `name` y `description`: el nombre identifica el skill y la descripción permite al asistente reconocer solicitudes pertinentes. El cuerpo define entrada, herramientas, procedimiento, criterios, límites y salida.

OpenCode descubre el skill y permite cargarlo mediante su herramienta nativa `skill`. En la comprobación realizada, la solicitud de auditar TiendaAndina no nombraba `consent-audit`; el asistente seleccionó y cargó el skill por el contexto de la tarea y por sus instrucciones especializadas.

Los recursos ejecutables y de conocimiento se mantienen dentro del mismo repositorio: `agente/`, `config/`, `evidencias/`, `rag_auditor.py` y `validar_skill.py`. El skill se distribuye con esos recursos, porque depende del motor del proyecto para ejecutar la auditoría.

## Identidad e instrucciones del asistente

La definición está en `.opencode/agent/consent-supervisor.md`.

| Componente | Definición |
|---|---|
| Identidad | Asistente Supervisor de Consentimientos, AGT-CONSENT-01 |
| Misión | Apoyar al auditor en la revisión documental del consentimiento |
| Instrucción de activación | Cargar `consent-audit` cuando corresponda la tarea |
| Conocimiento | Corpus, reglas, catálogo de excepciones y documentación del segundo entregable |
| Herramientas | Lectura de documentos, ejecución individual y herramientas MCP disponibles |
| Límites de actuación | Conservar el registro del motor y dejar las decisiones humanas al auditor |
| Permisos | Lecturas y comandos acotados; edición y delegación desactivadas |

El asistente no debe inventar una ejecución ni cambiar el hash, el identificador, el dictamen o el estado para hacer más clara una respuesta. Puede resumirlos por separado y debe conservar el registro original como evidencia del resultado.

## Procedimiento especializado

1. Identificar la evidencia y el alcance. Rechazar una entrada vacía y comprobar que el documento pueda leerse.
2. Ejecutar la revisión. El motor busca posibles excepciones del artículo 14 antes de evaluar los dominios de consentimiento.
3. Recuperar criterios del corpus y evaluar la información, la obtención y registro, y la modificación y revocación.
4. Comprobar el resultado. Una etiqueta sin contenido, una contradicción o la falta de contexto no habilitan la emisión automática. Las citas deben corresponder a texto contiguo de la evidencia.
5. Conservar el registro y aplicar la revisión humana cuando corresponda. Una excepción candidata se presenta como provisional; los estados pendientes deben permanecer pendientes.
6. Presentar el informe y un resumen con documento, dictámenes, hallazgos, medidas y estado de revisión.

En modo local, la recuperación utiliza BM25 y las reglas son deterministas. El motor admite Ollama como componente opcional; la demostración reproducible lo desactiva. El asistente de OpenCode se probó con ChatGPT Plus mediante autorización del usuario. Por tanto, esta prueba combina un asistente con modelo en línea y un motor local; no se describe como procesamiento íntegramente local.

## Conocimiento normativo configurado

El corpus contiene 20 resúmenes del equipo relacionados con seis controles de ISO/IEC 27701:2025 y artículos de la Ley N.° 29733. Las reglas se agrupan en tres dominios:

| Dominio | Aspectos observados |
|---|---|
| Información y propósito | Finalidad, destinatarios, conservación, identidad y canal de derechos |
| Obtención y registro | Mecanismo de aceptación, casillas premarcadas, aceptación agrupada y registro |
| Modificación y revocación | Mecanismo de retiro, canal y declaración del plazo de atención |

Los resúmenes no sustituyen las fuentes oficiales. El catálogo de excepciones es parcial y el reglamento no forma parte del corpus base distribuido. Antes de usar el resultado en una auditoría real se necesita contrastar la aplicabilidad y vigencia de los criterios. La etapa actual demuestra el procedimiento del skill sobre casos sintéticos y una cobertura delimitada.

## Validación funcional

La validación consta de dos evidencias complementarias. La conversación de OpenCode acredita que el asistente descubre y activa el skill, ejecuta la tarea y presenta un resultado. El comando `python validar_skill.py` comprueba el motor sobre cinco escenarios, conserva resultados por ejecución y no aprueba ni rechaza tickets automáticamente.

| Caso ficticio | Resultado global | Estado esperado |
|---|---|---|
| LibreríaSur, formulario completo | Conforme en los criterios evaluados | Emitido |
| TiendaAndina, incumplimientos y evidencia faltante | No Conforme | Pendiente de revisión |
| Banco Andino, excepción contractual candidata | No Conforme en información; obtención y revocación No Aplica provisionalmente | Pendiente de revisión |
| Formulario con encabezados vacíos | No Conforme por evidencia insuficiente | Pendiente de revisión |
| ClubFit, instrucción maliciosa incrustada | No Conforme | Pendiente de revisión |

La suite incluye 39 pruebas aprobadas. Entre las comprobaciones añadidas están los encabezados insuficientes, la falta de contexto, el rechazo de citas alteradas, el bloqueo de emisión de registros pendientes o fabricados, la unicidad de auditorías de una misma organización y la persistencia del ticket junto al registro.

Estos casos comprueban comportamientos concretos. No constituyen una estimación de exactitud general ni una validación jurídica independiente. Tampoco se presentan como resultados nuevos de la recuperación híbrida o de Ollama, que no se ejecutaron en esta demostración.

## Cómo repetir la demostración

Desde la raíz del repositorio, con Python y las dependencias instaladas:

```powershell
python validar_skill.py
pytest -q
```

Para probarlo desde OpenCode, abrir el proyecto, conectar un modelo con capacidad de herramientas y seleccionar `consent-supervisor`. Ejemplo de solicitud:

> Revisa el consentimiento descrito en evidencias/caso_insuficiente.txt, sigue el procedimiento especializado del proyecto e indica si el informe puede emitirse.

Comprobar en la sesión la carga de `consent-audit`, la ejecución de la auditoría y la presentación del estado pendiente. Después de modificar una definición del skill o del asistente, iniciar una sesión nueva de OpenCode para cargarla.

La configuración original mantiene MCP desactivado y permite la alternativa de consola. Para conectarlo, activar `consent-supervisor` en `opencode.json` y comprobar que `python` apunte al entorno donde está instalado MCP 1.x. La configuración de credenciales es local y no se incorpora al repositorio.

## Limitaciones y tercera unidad

Las reglas siguen siendo patrones y pueden rechazar redacciones válidas o aceptar afirmaciones insuficientes que no estén previstas. La revisión humana y el alcance explícito son necesarios. La bitácora usa archivos JSON y todavía requiere mejoras para múltiples procesos, protección de exportaciones y versionado integral de los insumos de decisión.

En la tercera unidad se abordarán el diseño agéntico completo, las integraciones con otros agentes, la orquestación, la automatización y la evaluación con fuentes verificadas y casos etiquetados de forma independiente. El código existente de recuperación híbrida se conserva como avance técnico; su presencia no se toma como una validación de esa etapa.

## Correspondencia con el segundo entregable

| Requisito de la pauta | Evidencia disponible |
|---|---|
| De prompt a skill | Transformación de la solicitud de referencia en un procedimiento reutilizable |
| Activación, estructura y pasos | `SKILL.md` y llamada observada a la herramienta `skill` |
| Identidad, instrucciones y conocimiento | Definición del asistente y recursos del repositorio |
| Resultado Skill funcional especializado | Conversación completa, motor ejecutable, casos reproducibles e informes |

## Referencias

- OpenCode. Agent Skills. https://opencode.ai/docs/skills/
- OpenCode. Agents. https://opencode.ai/docs/agents/
- Proyecto Auditoria. Código fuente, configuración y evidencias del equipo. https://github.com/Dan-Ar5/Auditoria
- International Organization for Standardization. ISO/IEC 27701:2025. https://www.iso.org/standard/27701
- Ley N.° 29733, versión publicada por la SMV. https://www.smv.gob.pe/Uploads/Ley_29733_vigente_2025.pdf
- Decreto Supremo N.° 016-2024-JUS, publicación oficial. https://www3.congreso.gob.pe/Docs/DGP/DIDP/files/ds_016-2024-jus.pdf
