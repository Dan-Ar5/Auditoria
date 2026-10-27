from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agente import build_agent, render_markdown

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]

_AGENT = None


def _agent():
    global _AGENT
    if _AGENT is None:
        _AGENT, _ = build_agent(mode=os.environ.get("RETRIEVER_MODE", "local"))
    return _AGENT


def mcp_tool_retrieve_norms(query: str, top_k: int = 4, norma: Optional[str] = None,
                            control: Optional[List[str]] = None, articulo: Optional[List[int]] = None,
                            naturaleza: Optional[str] = None) -> Dict[str, Any]:
    """Recupera fragmentos de la ISO/IEC 27701:2025 y la Ley N.° 29733 con filtros de metadatos."""
    filters = {"norma": norma, "control": control, "articulo": articulo, "naturaleza": naturaleza}
    return _agent().mcp.mcp_tool_retrieve_norms(query, top_k, {k: v for k, v in filters.items() if v}).to_dict()


def mcp_tool_check_exceptions(evidence_text: str) -> Dict[str, Any]:
    """Paso Fail-Fast: verifica si la evidencia encaja en una excepción del Art. 14 (Ley N.° 29733)."""
    return _agent().mcp.mcp_tool_check_exceptions(evidence_text).to_dict()


def mcp_tool_analyze_evidence(evidence_text: str) -> Dict[str, Any]:
    """Aplica las reglas de consentimiento por dominio y detecta instrucciones maliciosas en la evidencia."""
    return _agent().mcp.mcp_tool_analyze_evidence(evidence_text).to_dict()


def mcp_tool_emit_audit_report(audit_record: Dict[str, Any]) -> Dict[str, Any]:
    """Envía un informe de auditoría emitido a la Capa de Gobernanza."""
    return _agent().mcp.mcp_tool_emit_audit_report(audit_record).to_dict()


def mcp_tool_audit_consent(evidence_text: str, evidence_name: str = "evidencia.txt") -> Dict[str, Any]:
    """Auditoría completa: Fail-Fast, recuperación por dominio, dictamen, HITL e informe Markdown."""
    record = _agent().audit_evidence(evidence_text, evidence_name)
    return {"record": record, "markdown": render_markdown(record)}


def create_server():
    if FastMCP is None:
        raise RuntimeError("El paquete 'mcp' no está instalado. Ejecuta: pip install -r requirements.txt")
    server = FastMCP("consent-supervisor-mcp")
    server.tool()(mcp_tool_retrieve_norms)
    server.tool()(mcp_tool_check_exceptions)
    server.tool()(mcp_tool_analyze_evidence)
    server.tool()(mcp_tool_emit_audit_report)
    server.tool()(mcp_tool_audit_consent)
    return server


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
