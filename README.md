# AGT-CONSENT-01 — Agente Supervisor de Consentimientos (Auditoría de Sistemas)

Agente de auditoría de privacidad que evalúa evidencias documentales (formularios,
políticas de privacidad y registros) frente a la **ISO/IEC 27701:2025** y la
**Ley N.° 29733**. Usa RAG híbrido, un paso **Fail-Fast** sobre las excepciones
del Art. 14 y un punto de control humano (HITL) del auditor líder.

Controles cubiertos: **A.1.2.2** (propósito), **A.1.2.4** y **A.1.2.5** (obtener
y registrar el consentimiento), **A.1.3.3** y **A.1.3.4** (información al
titular), **A.1.3.5** (modificar o retirar el consentimiento). Ley N.° 29733:
**Arts. 5, 13.5, 14 y 18**.

## Flujo

```
evidencia ──► Fail-Fast (Art. 14) ──► ¿excepción?
                                      ├─ sí ─► dominios 2 y 3 = No Aplica
                                      └─ no ─► evaluación completa
     para cada dominio:
       recuperación híbrida (densa + BM25 → RRF → Cross-Encoder, filtros por control/artículo)
       reglas sobre la evidencia + LLM (4 pasos: exigencia → cita → brecha → veredicto)
       guardas: citas textuales verificadas, fragmentos realmente recuperados
     ──► informe JSON estandarizado ──► ¿observaciones? ─ sí ─► cola HITL (auditor)
                                                       └ no ─► bitácora de gobernanza
```

## Estructura

```
Auditoria/
├── agente/
│   ├── agent.py           # ConsentSupervisorAgent (Fail-Fast, dominios, informe)
│   ├── backends.py        # ConsentMCPBackend: herramientas MCP sobre el modo local o qdrant
│   ├── corpus.py          # Chunking estructural (artículo/numeral, control A/B) + metadatos
│   ├── retrieval.py       # LocalBM25Retriever + QdrantHybridRetriever (densa+BM25, RRF, Cross-Encoder)
│   ├── evidence.py        # EvidenceAnalyzer (reglas, negaciones, inyección) + ExceptionCatalog (Art. 14)
│   ├── reasoner.py        # OllamaReasoner (JSON con esquema, temperatura 0.0)
│   ├── hitl.py            # Cola persistente del auditor + log de gobernanza
│   ├── exporters.py       # Markdown / JSON / CSV / Excel + matriz de evidencias
│   ├── factory.py         # build_agent(): arma el agente completo
│   └── models.py          # Dominios, controles, dictámenes
├── config/
│   ├── corpus_normativo.json   # Corpus base resumido (ISO + Ley) con metadatos del TIF
│   ├── consent_rules.json      # Reglas por dominio + patrones de inyección
│   └── excepciones_art14.json  # Catálogo de excepciones para el Fail-Fast
├── evidencias/            # Casos a auditar (.txt)
├── .opencode/             # Agente (consent-supervisor) y skill (consent-audit) para opencode
├── tests/test_agent.py
├── mcp_server.py          # MCP Server real (stdio) con las herramientas
├── run_demo.py            # Demo end-to-end (todas las evidencias)
├── rag_auditor.py         # Auditoría de una evidencia por consola
├── docs/                  # Historial de fases 0-1 y migración de Qdrant
└── requirements.txt
```

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

El núcleo (`agente/` en modo `local`) solo usa la librería estándar. Las
dependencias se necesitan para el modo `qdrant`, la lectura de PDF, el MCP
Server, Excel y las pruebas.

## Ejecución de la demo

```bash
python run_demo.py                 # modo local: sin Docker ni modelos
python run_demo.py --modo qdrant   # RAG híbrido completo (requiere Qdrant)
```

Audita los 4 casos de `evidencias/`:

| Caso | Qué demuestra | Resultado esperado |
|---|---|---|
| `caso_tiendaandina.txt` | El caso del TIF (secciones 3.6 y 3.7) | No Conforme en los 3 dominios |
| `caso_banco.txt` | Fail-Fast: excepción contractual (Art. 14) | Dominios 2 y 3 No Aplica, va al auditor |
| `caso_conforme.txt` | Un formulario bien diseñado | Conforme, se emite sin revisión |
| `caso_inyeccion.txt` | Instrucción maliciosa oculta (TIF 4.2.4) | No Conforme, va al auditor |

Genera en `out/`:

- `informe_<caso>.md`: informe con el formato de la tabla del TIF (3.7) y trazabilidad de fragmentos.
- `informes_draft.json` / `informes_draft.csv` / `informes_draft.xlsx`: dictámenes por dominio.
- `matriz_evidencias.json`: consultas al corpus, reglas, Fail-Fast y decisiones del auditor.
- `pending_reviews.json`: cola HITL.
- `informes_finales.json` y `governance_log.json`: consolidado tras la aprobación.

## Auditar una evidencia

```bash
python rag_auditor.py                                         # caso TiendaAndina
python rag_auditor.py --evidencia evidencias\caso_banco.txt
python rag_auditor.py --modo local                            # sin Docker
```

Para auditar otro caso basta con crear un `.txt` en `evidencias/`. Si incluye las
líneas `Empresa: ...` y `Alcance: ...`, se usan en el encabezado del informe.

## Modo qdrant (RAG híbrido del TIF)

```bash
python run_demo.py --modo qdrant
```

No necesita Docker: si no hay un servidor Qdrant en `localhost:6333`, usa Qdrant embebido en la
carpeta `.qdrant_local/`. Con Docker también funciona:
`docker run -d --name qdrant -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant`.

- Embeddings densos multilingües `paraphrase-multilingual-MiniLM-L12-v2` + BM25 en español, fusionados con RRF.
- Re-ranking con el Cross-Encoder multilingüe `BAAI/bge-reranker-v2-m3-int8` (unos 570 MB). Se desactiva con `set RERANKER=0`.
- La primera ejecución descarga los modelos en `.modelos/` e indexa el corpus en la colección `agt_consent_corpus`.
  Se reindexa sola cuando cambia el corpus (o con `--reindexar`). No toca la colección antigua `auditoria_iso_ley`.
- Variables opcionales: `QDRANT_URL`, `RETRIEVER_MODE`.

Si `rag_auditor.py` no encuentra Qdrant, continúa en modo local y lo avisa.

## Corpus normativo

`config/corpus_normativo.json` trae los controles y artículos del TIF
**resumidos por el equipo** (`tipo_texto: resumen`), porque la ISO/IEC 27701 está
protegida por derechos de autor. Para citas literales, copia los PDF oficiales en
`documentos_normativos/` (carpeta excluida del repositorio):

- El nombre define la norma: debe contener `29733`/`ley`, `27701`/`iso` o `016-2024`/`reglamento`.
- La ley se divide por artículo y los artículos largos, como el 14, por numeral, con la cabecera antepuesta.
- La ISO se divide por control (Anexo A = requisito, Anexo B = guía).
- Un PDF escaneado sin texto se omite y se avisa (el PDF actual de la ISO lo es; ver `docs/HISTORIAL_FASES_0_1.md`).
- Si el PDF de la ley trae pegado el reglamento antiguo, conviene separarlo: ambos tienen un "Artículo 14".

## MCP Server

```bash
python mcp_server.py
```

Expone por stdio: `mcp_tool_retrieve_norms`, `mcp_tool_check_exceptions`,
`mcp_tool_analyze_evidence`, `mcp_tool_emit_audit_report` y
`mcp_tool_audit_consent` (flujo completo). Para opencode, activarlo en `opencode.json`.

## LLM local (opcional)

Con Ollama en marcha, el agente redacta cada dominio con los 4 pasos de la Cadena
de Pensamiento (temperatura 0.0, salida JSON con esquema). Sin Ollama, usa un
fallback determinista basado en `config/consent_rules.json`.

```bash
ollama serve
ollama pull llama3
```

Modelo configurable con `set LLM_MODELO=llama3.1`. Las respuestas del LLM pasan por
guardas antes de usarse:
- si cita texto que no está en la evidencia o fragmentos no recuperados, va a revisión humana;
- si su dictamen contradice al de las reglas, se mantiene el de las reglas (verificable regla por regla),
  se adjunta la opinión del LLM al informe y el informe va a revisión humana.

Evaluación con llama3 en esta PC (4 casos de Fail-Fast + 6 dominios): llama3 acertó 8/10 y llama3.1 6/10.
Los modelos de 8B tienden a dictaminar "No Conforme" en casos que cumplen; por eso el LLM es una segunda
opinión y no la última palabra.

## Revisión humana (HITL)

Un informe queda en `PENDIENTE_REVISION_AUDITOR`, en vez de emitirse, cuando:
- se aplicó una excepción del Art. 14;
- se detectan instrucciones maliciosas en la evidencia;
- el LLM discrepa de las reglas;
- el LLM inventa citas;
- la confianza del LLM es baja.

## Pruebas

```bash
pytest -q
```
