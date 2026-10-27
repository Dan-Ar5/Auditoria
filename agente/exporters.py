from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPORT_COLUMNS = [
    "audit_id",
    "organization",
    "domain",
    "controls",
    "articles",
    "dictamen",
    "evidencia_citada",
    "hallazgo",
    "medida_correctiva",
    "fragments",
    "source",
    "overall_status",
    "review_status",
    "evidence_sha256",
    "generated_at",
]


def rows_from_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        for domain in record.get("domains", []):
            rows.append({
                "audit_id": record.get("audit_id"),
                "organization": record.get("subject", {}).get("organization"),
                "domain": domain.get("domain"),
                "controls": "; ".join(domain.get("controls", [])),
                "articles": "; ".join(f"Art. {a}" for a in domain.get("articles", [])),
                "dictamen": domain.get("dictamen"),
                "evidencia_citada": " | ".join(domain.get("evidencia_citada", [])),
                "hallazgo": domain.get("hallazgo"),
                "medida_correctiva": domain.get("medida_correctiva"),
                "fragments": "; ".join(domain.get("fragments", [])),
                "source": domain.get("source"),
                "overall_status": record.get("overall_status"),
                "review_status": record.get("review_status"),
                "evidence_sha256": record.get("subject", {}).get("evidence_sha256"),
                "generated_at": record.get("generated_at"),
            })
    return rows


def export_json(records: Iterable[Dict[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(json.dumps(list(records), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def export_csv(records: Iterable[Dict[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_from_records(records))
    return target


def export_xlsx(records: Iterable[Dict[str, Any]], path: str | Path) -> Path:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl es requerido para exportar Excel. Instala requirements.txt") from exc
    target = Path(path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Dictamenes"
    sheet.append(REPORT_COLUMNS)
    for row in rows_from_records(records):
        sheet.append([row[column] for column in REPORT_COLUMNS])
    workbook.save(target)
    return target


def _cell(text: Any) -> str:
    return str(text if text is not None else "-").replace("|", "/").replace("\n", " ")


def render_markdown(record: Dict[str, Any]) -> str:
    """Informe de auditoría con el formato de la sección 3.7 del TIF."""
    subject = record["subject"]
    fail_fast = record["fail_fast"]
    lines = [
        f"# Informe de auditoría de consentimiento – {subject['organization']}",
        "",
        f"- **ID:** {record['audit_id']} · **Agente:** {record['agent_id']} · **Fecha:** {record['generated_at']}",
        f"- **Alcance:** {subject['scope']}",
        f"- **Marco:** {' y '.join(record['framework'])}",
        f"- **Evidencia:** `{subject['evidence_file']}` · SHA-256 `{subject['evidence_sha256']}`",
        f"- **Motor:** recuperación `{record['engine']['retriever']}` · LLM {record['engine']['llm']} "
        f"(temperatura {record['engine']['temperature']})",
        f"- **Resultado global:** {record['overall_status']} · **Estado:** {record['review_status']}",
        "",
        "## Verificación Fail-Fast (Art. 14, Ley N.° 29733)",
        "",
        f"{'Se identificó' if fail_fast['exception_applies'] else 'No se identificó'} una excepción aplicable "
        f"(fuente: {fail_fast['source']}). {fail_fast['justification']}",
        "",
        "## Dictamen por dominios",
        "",
        "| Dominio evaluado | Requisito / Norma | Evidencia auditada | Dictamen | Hallazgo técnico y medida correctiva |",
        "|---|---|---|---|---|",
    ]
    for domain in record["domains"]:
        norms = []
        if domain.get("controls"):
            norms.append("ISO/IEC 27701: " + ", ".join(domain["controls"]))
        if domain.get("articles"):
            norms.append("Ley 29733: " + ", ".join(f"Art. {a}" for a in domain["articles"]))
        evidence = " / ".join(f"«{q}»" for q in domain.get("evidencia_citada", [])) or "Sin evidencia aportada"
        lines.append(
            f"| {_cell(domain['domain'])} | {_cell('. '.join(norms))} | {_cell(evidence)} | **{_cell(domain['dictamen'])}** | "
            f"**Hallazgo:** {_cell(domain['hallazgo'])}<br>**Medida:** {_cell(domain['medida_correctiva'])}<br>"
            f"_Fragmentos: {_cell(', '.join(domain.get('fragments', [])))}_ |"
        )
    lines += ["", "## Medidas correctivas priorizadas", ""]
    lines += [f"{i}. {action}" for i, action in enumerate(record["corrective_actions"], 1)] or ["Ninguna."]
    lines += ["", "## Revisión humana (HITL)", "",
              f"- Requiere revisión del auditor: **{'Sí' if record['hitl_trigger']['requires_auditor_signoff'] else 'No'}**",
              f"- Motivo: {record['hitl_trigger']['reason']}"]
    if record["hitl_trigger"].get("ticket"):
        lines.append(f"- Ticket: `{record['hitl_trigger']['ticket']}`")
    lines += ["", "## Trazabilidad de fragmentos recuperados", "",
              "| Dominio | Fragmento | Norma | Control / Artículo | Naturaleza | Texto | Origen | Puntaje |",
              "|---|---|---|---|---|---|---|---|"]
    for item in record["traceability"]:
        ref = item.get("control") or (f"Art. {item['articulo']}" + (f" num. {item['numeral']}" if item.get("numeral") else "")
                                      if item.get("articulo") else "-")
        lines.append(f"| {_cell(item['domain'])} | {item['fragment_id']} | {_cell(item['norma'])} | {_cell(ref)} | "
                     f"{_cell(item.get('naturaleza'))} | {_cell(item.get('tipo_texto'))} | {_cell(item.get('origen'))} | "
                     f"{_cell(item.get('score'))} |")
    lines += ["", "## Evidencia auditada", "", "```text", record["evidence_text"], "```", ""]
    return "\n".join(lines)


def export_markdown(record: Dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(render_markdown(record), encoding="utf-8")
    return target


def build_evidence_matrix(
    records: Iterable[Dict[str, Any]],
    call_log: Iterable[Any],
    decisions: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for response in call_log:
        payload = response.to_dict() if hasattr(response, "to_dict") else dict(response)
        if payload.get("tool") == "mcp_tool_retrieve_norms" and payload.get("ok"):
            data = payload.get("data", {})
            evidence.append({
                "audit_id": None,
                "control": "Recuperación",
                "evidence_type": "Consulta al corpus normativo",
                "detail": f"Filtros {data.get('filters')} -> {[r['id'] for r in data.get('results', [])]}",
                "reference": payload.get("tool"),
            })
    for record in records:
        audit_id = record.get("audit_id")
        evidence.append({
            "audit_id": audit_id,
            "control": "Ley 29733 Art. 14",
            "evidence_type": "Verificación Fail-Fast",
            "detail": record["fail_fast"]["justification"],
            "reference": ", ".join(record["fail_fast"]["fragments"]),
        })
        for domain in record.get("domains", []):
            for finding in domain.get("rule_findings", []):
                evidence.append({
                    "audit_id": audit_id,
                    "control": ", ".join(domain.get("controls", [])) or "Art. 14",
                    "evidence_type": "Regla sobre la evidencia",
                    "detail": f"{finding['id']} {finding['description']}: {finding['status']}",
                    "reference": finding.get("quote"),
                })
            evidence.append({
                "audit_id": audit_id,
                "control": ", ".join(domain.get("controls", [])) or "Art. 14",
                "evidence_type": "Dictamen de dominio",
                "detail": f"{domain['domain']}: {domain['dictamen']}",
                "reference": ", ".join(domain.get("fragments", [])),
            })
    for decision in decisions:
        evidence.append({
            "audit_id": decision.get("audit_id"),
            "control": "HITL",
            "evidence_type": "Decisión del auditor",
            "detail": f"{decision.get('status')} por {decision.get('approver')}: {decision.get('note', '')}",
            "reference": decision.get("decided_at"),
        })
    return evidence
