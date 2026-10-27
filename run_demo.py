from __future__ import annotations

import argparse
import json
from pathlib import Path

from agente import (build_agent, build_evidence_matrix, export_csv, export_json, export_markdown, export_xlsx)

BASE_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = BASE_DIR / "evidencias"
OUT_DIR = BASE_DIR / "out"


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo end-to-end del Supervisor de Consentimientos (AGT-CONSENT-01)")
    parser.add_argument("--modo", choices=["local", "qdrant"], default=None,
                        help="motor de recuperación (por defecto RETRIEVER_MODE o 'local')")
    parser.add_argument("--reindexar", action="store_true", help="reconstruye el índice en Qdrant")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    for stale in ("pending_reviews.json", "governance_log.json", "informes_finales.json"):
        (OUT_DIR / stale).unlink(missing_ok=True)  # cada demo parte de una cola limpia

    agent, info = build_agent(mode=args.modo, out_dir=OUT_DIR, rebuild_index=args.reindexar)
    backend, hitl = agent.mcp, agent.hitl_queue

    print(f"[i] Ollama disponible: {agent.reasoner.is_available()} (modelo={agent.reasoner.model})")
    print(f"[i] Recuperación: {backend.mode} | fragmentos en el corpus: {len(backend.corpus)}")
    for item in info["ingest"]:
        print(f"    - {item['source']}: {item['fragments']} fragmentos ({item['status']})")
    if info.get("reranker_error"):
        print(f"[!] Cross-Encoder no disponible, se usa solo RRF: {info['reranker_error']}")

    records = []
    for evidence_file in sorted(EVIDENCE_DIR.glob("*.txt")):
        record = agent.audit_evidence(evidence_file.read_text(encoding="utf-8"), evidence_file.name)
        export_markdown(record, OUT_DIR / f"informe_{evidence_file.stem}.md")
        records.append(record)
        verdicts = " | ".join(f"{d['domain'].split('.')[0]}:{d['dictamen']}" for d in record["domains"])
        print(f"\n[auditoría] {record['audit_id']} ({evidence_file.name}) -> {record['overall_status']} "
              f"[{record['review_status']}]\n    {verdicts}")

    export_json(records, OUT_DIR / "informes_draft.json")
    export_csv(records, OUT_DIR / "informes_draft.csv")
    try:
        export_xlsx(records, OUT_DIR / "informes_draft.xlsx")
        xlsx_status = "informes_draft.xlsx"
    except RuntimeError as exc:
        xlsx_status = f"no disponible ({exc})"

    print("\n[cola HITL]")
    pending = hitl.list_pending()
    for item in pending:
        print(f"  - {item['ticket']}: {item['record']['audit_id']} -> {item['record']['hitl_trigger']['reason']}")
    if not pending:
        print("  (vacía)")

    # Simulación del auditor líder: aprueba el primer ticket y rechaza el último.
    tickets = [item["ticket"] for item in pending]
    if tickets:
        hitl.approve(tickets[0], approver="auditor.lider@empresa.com", note="Excepción verificada contra el contrato.")
    if len(tickets) > 1:
        hitl.reject(tickets[-1], approver="auditor.lider@empresa.com",
                    note="Evidencia manipulada: se solicita el formulario original al auditado.")

    evidence = build_evidence_matrix(records, backend.call_log, hitl.decisions)
    export_json(evidence, OUT_DIR / "matriz_evidencias.json")
    approved = hitl.consolidate()
    emitted = [entry["audit_id"] for entry in hitl.governance.entries]

    print(f"\n[entregables] {len(records)} evidencias auditadas en out/")
    print(f"  - informe_<caso>.md (uno por evidencia)")
    print(f"  - informes_draft.json / informes_draft.csv / {xlsx_status}")
    print(f"  - matriz_evidencias.json ({len(evidence)} evidencias)")
    print(f"  - pending_reviews.json, informes_finales.json ({len(approved)} aprobados), governance_log.json")
    print(f"\n[gobernanza] informes emitidos en la bitácora:")
    print(json.dumps(emitted, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
