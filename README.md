# Supervisor de Consentimientos (RAG híbrido) — avance

Prototipo del agente descrito en el TIF: audita una evidencia (formulario, política de privacidad) contra la ISO/IEC 27701:2025 y la Ley N.° 29733 con un LLM local.

## Qué hace hoy `rag_auditor.py`

1. **Ingesta**: lee los PDF de `documentos_normativos/`, los divide en fragmentos (~800 caracteres, 15 % de solapamiento) y guarda con cada uno sus metadatos: norma, página, artículos, controles ISO y naturaleza (`excepcion`, `requisito_normativo`, `guia`). Avisa y omite los PDF escaneados sin texto.
2. **Búsqueda híbrida**: embeddings multilingües (`paraphrase-multilingual-MiniLM-L12-v2`) + BM25 en español, fusionados con RRF dentro de Qdrant.
3. **Fail-Fast**: primero recupera solo fragmentos del Art. 14 marcados como excepción y pregunta al LLM si aplica alguna. Si aplica, no evalúa el dominio de consentimiento.
4. **Evaluación por dominio**: una búsqueda por cada dominio del TIF (información, obtención/registro, revocación) y un dictamen en tabla con Conforme / No Conforme / No Aplica, citando los fragmentos `[F#]`.
5. **Trazabilidad**: guarda en `reportes/` un informe Markdown con hash SHA-256 de la evidencia, el resultado del Fail-Fast, el dictamen y la tabla de fragmentos usados.

Pendiente respecto al TIF: re-ranking con Cross-Encoder, chunking estructural por artículo/control y la ingesta de la ISO (su PDF es escaneado y `pypdf` no extrae texto).

## Cómo ejecutarlo

Requisitos: Python 3.10+, Docker con Qdrant y Ollama con `llama3`.

```powershell
# 1. Qdrant (si ya existe el contenedor, basta con: docker start <nombre>)
docker run -d --name qdrant -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant

# 2. Modelo local
ollama pull llama3

# 3. Entorno de Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. Copiar los PDF normativos a documentos_normativos\ (el nombre define la norma:
#    que contenga "29733"/"ley", "27701"/"iso" o "016-2024"/"reglamento")

# 5. Ejecutar
python rag_auditor.py                                         # caso TiendaAndina del TIF
python rag_auditor.py --evidencia evidencias\caso_banco.txt   # otro caso
python rag_auditor.py --reindexar                             # si cambiaste los PDF
```

La primera ejecución descarga los modelos de embeddings (~250 MB) en `.modelos/` e indexa los PDF; las siguientes reutilizan el índice. Para auditar otro caso basta con crear un `.txt` en `evidencias/`.

El script usa la colección `supervisor_consentimientos`. **No toca ni borra la colección original `auditoria_iso_ley`** (la del respaldo descrito abajo). Variables opcionales: `QDRANT_URL`, `OLLAMA_URL`, `LLM_MODELO`.

Si el PDF de la ley incluye también el reglamento antiguo (caso del PDF mixto descrito abajo), conviene separarlo: el reglamento también tiene un "Artículo 14" y el filtro del Fail-Fast los mezclaría.

---

# Historial: avance de fases 0 y 1

Fecha: 28 de septiembre de 2026. Este directorio contiene respaldos, utilidades y resultados del trabajo sobre el prototipo existente. No es una implementación nueva del auditor. Los originales `rag_auditor.py`, `requirements.txt`, los PDF originales y el entorno virtual no fueron modificados.

## Estado real

| Componente | Estado | Evidencia y límite |
|---|---|---|
| Qdrant original | VERIFICADO | 1.19.1, colección `auditoria_iso_ley`, 249 puntos, dimensión 384, Cosine. Comparación de IDs, payloads y vectores con el export: idénticos. |
| Snapshot descargado | VERIFICADO | 1.435.136 bytes; SHA-256 coincide con el servidor; archivo tar leído íntegramente, 16 miembros. |
| Restauración del snapshot | NO_VERIFICADO | No se ha restaurado en otra instancia. No confundir integridad del archivo con recuperabilidad probada. |
| Persistencia Qdrant | NO_VERIFICADO | El contenedor actual no tiene montajes. Procedimiento preparado y pendiente de autorización. |
| Python existente | VERIFICADO | `C:\Users\jhast\venv_auditoria\Scripts\python.exe`, Python 3.14.2; no se instalaron paquetes ni se creó otro entorno. |
| PDF mixto | VERIFICADO | Portada p. 1; ley pp. 2–11; reglamento histórico pp. 12–31. Separación lógica por encabezados del contenido. |
| Consolidación vigente de la ley | NO_VERIFICADO | El archivo no acredita por sí solo la fecha de todas sus modificaciones. `active=false` preventivo en el corpus preparado; no significa que la Ley esté derogada. |
| DS 016-2024-JUS | VERIFICADO | PDF de publicación oficial, 24/24 páginas con texto; número, referencia a Ley 29733 y derogación del DS 003-2013-JUS comprobados. No se ha certificado exhaustivamente la ausencia de modificaciones posteriores. |
| Extracción pypdf de ISO | FALLÓ | 0/72 páginas con texto, confirmado. No se usa como extracción suficiente. |
| OCR local ISO | VERIFICADO | 72 páginas procesadas, 71 con texto, cobertura bruta 98,61%. La página 71 está en blanco, comprobado visualmente. |
| Calidad completa del OCR | NO_VERIFICADO | Español `es-ES` porque no hay OCR inglés instalado. Omisiones de identificadores y orden de columnas detectados. |
| Controles ISO revisados | VERIFICADO | 7 filas comparadas visualmente contra pp. PDF 21–22; correcciones y hashes documentados. No equivale a certificar toda la ISO. |
| Corpus listo para auditoría automática | NO_VERIFICADO | Estado funcional `CORPUS_INSUFICIENTE`. |
| TIF | VERIFICADO | Texto de sus seis páginas leído; PDF conservado sin cambios. Recomendaciones separadas. |
| Embeddings, reranking y fases 2–11 | NO_VERIFICADO | No se han elegido modelos, creado V2, ejecutado ingesta ni medido Recall@K. |

Las fases 0 y 1 **no se declaran cerradas**. La fase 0 espera autorización para la transición de contenedor; la fase 1 necesita completar la validación del corpus. Las pruebas exitosas comprueban los resultados y la detección de límites, no convierten un corpus incompleto en listo.

## Respaldo

Directorio: `backup-20260928T211750Z/`.

- Snapshot: `auditoria_iso_ley-465272179526703-2026-09-28-21-17-51.snapshot`.
- SHA-256: `b98a8a7299fa514cf114d22a293386f6998cfc9b5ba3e93a0a2044d0ec84abec`.
- `points-with-vectors.json`: export adicional de los 249 puntos.
- `manifest.json`: tamaño, checksum del servidor, versión y recuentos antes/después.
- `offline-validation.json`: revisión del archivo y dimensiones.
- `qdrant-live-verification.json`: comparación real del servidor con el export.

El snapshot permanece también en el almacenamiento del contenedor original. La copia de esta carpeta es independiente de ese contenedor. No se eliminó ningún snapshot. Conviene conservar esta carpeta con acceso local restringido; el respaldo incluye los textos normativos indexados y no debe publicarse.

`backup_qdrant.ps1` repite el respaldo mediante la API local, sin borrar ni recrear colecciones. El script comprueba tamaño, SHA-256 y recuentos. La versión exacta de Qdrant y su configuración previa están guardadas en `docker-inspect-before.json` y `docker-image-before.json`.

## Migración pendiente de autorización

Ver `MIGRACION_QDRANT.md` y `persistencia_pendiente.ps1`. No se ejecutó la migración. El script exige `-AutorizadoPorUsuario` y se probó que, sin ese argumento, se detiene antes de cualquier operación Docker.

Se conservará el contenedor original detenido como reversión. Se creará un único reemplazo activo con named volume y el mismo Qdrant 1.19.1, fijado por ID de imagen local. El puerto 6333 quedará limitado a `127.0.0.1`, compatible con Python local. No se tocarán iTop/i-doit, Snipe-IT, sus bases ni otros recursos.

## Corpus preparado

- `corpus/DS-016-2024-JUS.pdf`: descarga del documento público oficial. SHA-256 `7c538dd4e5af0f47a5d3b4a45fd896479e444f1e2eb85cbca8117c3047658b9d`.
- `corpus/ds016-extracted.json`: texto por página sin alterar el PDF.
- `corpus/ds016-validation.json`: procedencia y comprobaciones.
- `corpus/mixed-document-segments.json`: ley y reglamento histórico separados lógicamente, manteniendo páginas originales y hash. No es todavía el parser de artículos de fase 2. Los números de artículos son candidatos detectados, no una afirmación de cobertura jurídica completa.
- `corpus/iso-ocr-pages.json`: OCR sin corregir, con palabras, coordenadas, páginas y hashes de imágenes. Se conserva para reproducibilidad y revisión de tablas.
- `corpus/iso-control-candidates.json`: 75 identificadores candidatos de la columna de referencias del anexo A. Normalización `I/l` → `1` limitada a identificadores y registrada junto al valor original. No son 75 controles validados.
- `corpus/iso-reviewed-controls.json`: siete controles revisados: A.1.2.2, A.1.2.3, A.1.2.4, A.1.2.5, A.1.3.3, A.1.3.4 y A.1.3.5. Página física del PDF y página impresa se distinguen. Textos contrastados visualmente por Codex, sin revisión humana independiente.
- `corpus/iso-coverage.json` y `corpus/corpus-status.json`: cobertura, problemas y bloqueo explícito de disponibilidad.

Métricas ISO: `total_pages=72`, `text_pages=0` (extracción nativa), `ocr_pages=72`, `ocr_text_pages=71`, `controls_detected=75` (candidatos), `controls_reviewed=7`, `controls_indexed=0`, `extraction_coverage=98.61`. No hubo escritura a Qdrant ni creación de `auditoria_privacidad_v2`.

El OCR detecta texto pero no reconstruye automáticamente las filas: leer primero todos los IDs y después todas las descripciones mezclaría controles. Un ejemplo verificable de omisión es A.1.4.4, visible en la página PDF 22 pero ausente como identificador reconocido. La próxima corrección debe reconstruir filas mediante coordenadas y validar cada control que se vaya a usar, o incorporar OCR inglés local y repetir la validación. No se instaló un paquete de idioma de Windows.

## Reproducción local

En PowerShell, desde esta carpeta, con las rutas locales existentes:

```powershell
& .\reproduce_corpus.ps1
```

El script verifica que los originales coinciden con los hashes revisados, intenta extracción nativa con el Python existente, renderiza a PNG con el Poppler ya disponible, aplica `Windows.Media.Ocr` y vuelve a validar. No descarga archivos ni llama a un servicio remoto. Requiere los archivos guardados de esta carpeta y los originales en sus rutas actuales; se detiene si cambian. Se pueden indicar `-Python` y `-PdfToPpm` para rutas equivalentes. No modifica las fuentes ni los archivos de la aplicación.

Se usa Windows PowerShell 5.1 para WinRT; `-ExecutionPolicy Bypass` se limita a ese proceso, sin cambiar la política persistente del sistema. El reconocimiento usa el idioma instalado `es-ES`; las limitaciones quedan en el reporte. Los PNG son intermedios bajo `work/` y se pueden regenerar. Los textos OCR y sus coordenadas quedan conservados en `corpus/`.

Pruebas con la biblioteca estándar, sin instalar pytest:

```powershell
& 'C:\Users\jhast\venv_auditoria\Scripts\python.exe' -B -X utf8 -m unittest discover -s . -p 'test_phase01.py' -v
& 'C:\Users\jhast\venv_auditoria\Scripts\python.exe' -B -X utf8 .\verify_qdrant.py .\backup-20260928T211750Z
```

Resultado: 8 pruebas pasaron, 0 fallaron, 0 omitidas. El procedimiento `reproduce_corpus.ps1` también se ejecutó de principio a fin, volvió a renderizar y reconocer las 72 páginas y repitió las ocho pruebas con éxito; registro en `reproduction-results.txt`. Se comprobaron originales, snapshot/export, separación histórica, reglamento, cobertura OCR, procedencia de controles, estado de corpus y bloqueo de migración sin permiso. La comparación en vivo verificó IDs, payloads y vectores de los 249 puntos. El reinicio con persistencia todavía NO está probado.

## Fuentes técnicas y documentales públicas

- [Publicación oficial del DS 016-2024-JUS](https://www.gob.pe/institucion/smv/normas-legales/6426760-016-2024-jus).
- [Snapshots de Qdrant](https://qdrant.tech/documentation/operations/snapshots/).
- [API de recuperación de snapshots](https://api.qdrant.tech/api-reference/snapshots/recover-from-snapshot).
- [Ejemplo oficial de Windows OCR](https://learn.microsoft.com/en-us/samples/microsoft/windows-universal-samples/ocr/).

Solo se consultó documentación pública y se descargó el reglamento oficial. Los PDF locales, sus textos y las evidencias no se enviaron a servicios de OCR o inferencia externos.
