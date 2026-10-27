"""
Supervisor de Consentimientos (AGT-CONSENT-01): auditoría de UNA evidencia.

El agente vive en el paquete `agente/`; este script es el punto de entrada por consola.
Para auditar todos los casos de `evidencias/` y generar todos los entregables: python run_demo.py

Uso:
  python rag_auditor.py                                         # caso TiendaAndina del TIF
  python rag_auditor.py --evidencia evidencias/caso_banco.txt
  python rag_auditor.py --modo local                            # sin Docker (BM25 en Python)
  python rag_auditor.py --reindexar                             # si cambiaste los PDF
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agente import OUT_DIR, build_agent, export_json, export_markdown, render_markdown

DEFAULT_EVIDENCE = Path(__file__).resolve().parent / "evidencias" / "caso_tiendaandina.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Supervisor de Consentimientos (RAG híbrido + Fail-Fast)")
    parser.add_argument("--evidencia", default=str(DEFAULT_EVIDENCE), help="archivo .txt con la evidencia a auditar")
    parser.add_argument("--modo", choices=["local", "qdrant"], default="qdrant",
                        help="qdrant: densa+BM25+RRF+Cross-Encoder (por defecto); local: BM25 sin Docker")
    parser.add_argument("--reindexar", action="store_true", help="reconstruye el índice en Qdrant")
    args = parser.parse_args()

    evidence_path = Path(args.evidencia)
    if not evidence_path.exists():
        sys.exit(f"[!] No existe el archivo de evidencia '{evidence_path}'.")

    try:
        agent, info = build_agent(mode=args.modo, rebuild_index=args.reindexar)
    except Exception as exc:  # noqa: BLE001 - Qdrant caído o dependencias faltantes
        if args.modo != "qdrant":
            raise
        print(f"[!] No se pudo usar Qdrant ({exc}).\n    Se continúa en modo local (BM25, sin Docker).\n")
        agent, info = build_agent(mode="local")

    print(f"[i] Recuperación: {agent.mcp.mode} ({info['location']}) | índice: {info['index']}")
    for item in info["ingest"]:
        print(f"    - {item['source']}: {item['fragments']} fragmentos ({item['status']})")
    if info.get("reranker_error"):
        print(f"[!] Cross-Encoder no disponible, se usa solo RRF: {info['reranker_error']}")
    print(f"[i] LLM: {agent.reasoner.model if agent.reasoner.is_available() else 'Ollama no disponible -> fallback determinista'}")
    print(f"[i] Auditando {evidence_path.name}...\n")

    record = agent.audit_evidence(evidence_path.read_text(encoding="utf-8"), evidence_path.name)
    report_path = export_markdown(record, OUT_DIR / f"informe_{evidence_path.stem}.md")
    export_json([record], OUT_DIR / f"informe_{evidence_path.stem}.json")

    print(render_markdown(record))
    print("==============================================")
    print(f"Informe Markdown: {report_path}")
    print(f"Registro JSON:    {OUT_DIR / f'informe_{evidence_path.stem}.json'}")
    print(f"Estado:           {record['review_status']}"
          + (f" (ticket {record['hitl_trigger']['ticket']})" if record['hitl_trigger'].get('ticket') else ""))
    print("==============================================")


if __name__ == "__main__":
    main()
