from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .corpus import NormativeCorpus
from .evidence import EvidenceAnalyzer, ExceptionCatalog
from .hitl import GovernanceLog
from .models import ESTADO_EMITIDO, MCPResponse
from .retrieval import build_retriever

EXCEPTION_FILTER = {"articulo": 14, "naturaleza": "excepcion"}


class ConsentMCPBackend:
    """Bus de herramientas MCP del agente. El modo define el motor de recuperación (local o qdrant)."""

    def __init__(
        self,
        corpus: NormativeCorpus,
        analyzer: EvidenceAnalyzer,
        exceptions: ExceptionCatalog,
        governance_log: Optional[GovernanceLog] = None,
        mode: str = "local",
        **retriever_kwargs: Any,
    ) -> None:
        self.corpus = corpus
        self.analyzer = analyzer
        self.exceptions = exceptions
        self.governance_log = governance_log or GovernanceLog()
        self.mode = mode
        self.retriever = build_retriever(mode, corpus, **retriever_kwargs)
        self.call_log: List[MCPResponse] = []
        self._emittable_reports: Dict[str, Dict[str, Any]] = {}

    def index(self, rebuild: bool = False) -> Dict[str, Any]:
        return self.retriever.index(rebuild=rebuild)

    def mcp_tool_retrieve_norms(self, query: str, top_k: int = 4,
                                filters: Optional[Dict[str, Any]] = None) -> MCPResponse:
        """Recupera fragmentos normativos (híbrida en qdrant, BM25 en local) con filtros de metadatos."""
        try:
            results = self.retriever.search(query, top_k=top_k, filters=filters)
        except Exception as exc:  # noqa: BLE001
            return self._logged(MCPResponse("mcp_tool_retrieve_norms", False, None, str(exc)))
        return self._logged(MCPResponse("mcp_tool_retrieve_norms", True,
                                        {"query": query[:200], "filters": filters, "results": results}))

    def mcp_tool_check_exceptions(self, evidence_text: str) -> MCPResponse:
        """Paso Fail-Fast: contrasta la evidencia con las excepciones del Art. 14 (Ley N.° 29733)."""
        result = self.exceptions.check(evidence_text)
        retrieved = self.retriever.search("limitaciones y excepciones al consentimiento. " + evidence_text[:600],
                                          top_k=5, filters=EXCEPTION_FILTER)
        # El numeral que activó la regla debe estar en el contexto, primero.
        if result["matched"]:
            for fragment in self.retriever.search(result["matched"][0]["description"], top_k=1,
                                                  filters=EXCEPTION_FILTER):
                retrieved = [fragment] + [f for f in retrieved if f["id"] != fragment["id"]][:4]
        return self._logged(MCPResponse("mcp_tool_check_exceptions", True, {**result, "fragments": retrieved}))

    def mcp_tool_analyze_evidence(self, evidence_text: str) -> MCPResponse:
        """Aplica las reglas deterministas por dominio y detecta instrucciones maliciosas en la evidencia."""
        return self._logged(MCPResponse("mcp_tool_analyze_evidence", True, {
            "findings": self.analyzer.analyze(evidence_text),
            "injection_suspects": self.analyzer.detect_injection(evidence_text),
        }))

    def mcp_tool_emit_audit_report(self, audit_record: Dict[str, Any]) -> MCPResponse:
        """Emite únicamente un informe íntegro generado y habilitado por el flujo del agente."""
        audit_id = audit_record.get("audit_id")
        staged = self._emittable_reports.get(audit_id) if isinstance(audit_id, str) else None
        if (staged is None or staged != audit_record or audit_record.get("review_status") != ESTADO_EMITIDO
                or audit_record.get("hitl_trigger", {}).get("requires_auditor_signoff") is not False):
            return self._logged(MCPResponse("mcp_tool_emit_audit_report", False, {"stored": False},
                                           "El informe no está habilitado para emisión; complete el flujo de auditoría y revisión."))
        self.governance_log.append(deepcopy(staged))
        del self._emittable_reports[audit_id]
        return self._logged(MCPResponse("mcp_tool_emit_audit_report", True,
                                        {"stored": True, "log_size": len(self.governance_log.entries)}))

    def _stage_generated_report(self, record: Dict[str, Any]) -> None:
        """Registro interno, no expuesto como herramienta MCP."""
        if (record.get("review_status") == ESTADO_EMITIDO
                and record.get("hitl_trigger", {}).get("requires_auditor_signoff") is False):
            self._emittable_reports[record["audit_id"]] = deepcopy(record)

    def _logged(self, response: MCPResponse) -> MCPResponse:
        self.call_log.append(response)
        return response


def build_backend(mode: Optional[str] = None, **kwargs: Any) -> ConsentMCPBackend:
    mode = mode or os.environ.get("RETRIEVER_MODE", "local")
    if mode == "qdrant":
        kwargs.setdefault("url", os.environ.get("QDRANT_URL", "http://localhost:6333"))
        if os.environ.get("RERANKER", "1") == "0":
            kwargs["reranker_model"] = None
    return ConsentMCPBackend(mode=mode, **kwargs)
