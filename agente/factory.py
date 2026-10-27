from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .agent import ConsentSupervisorAgent
from .backends import build_backend
from .corpus import NormativeCorpus
from .evidence import EvidenceAnalyzer, ExceptionCatalog
from .hitl import GovernanceLog, HITLQueue
from .reasoner import OllamaReasoner

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DOCS_DIR = BASE_DIR / "documentos_normativos"
OUT_DIR = BASE_DIR / "out"


def build_corpus(include_pdfs: bool = True) -> NormativeCorpus:
    """Corpus base (config/corpus_normativo.json) + PDF de documentos_normativos/ si existen."""
    corpus = NormativeCorpus.from_file(CONFIG_DIR / "corpus_normativo.json")
    if include_pdfs and DOCS_DIR.exists() and any(DOCS_DIR.glob("*.pdf")):
        try:
            corpus.add_pdf_folder(DOCS_DIR)
        except RuntimeError as exc:  # pypdf no instalado
            corpus.ingest_report.append({"source": DOCS_DIR.name, "fragments": 0, "status": f"omitido: {exc}"})
    return corpus


def build_agent(
    mode: Optional[str] = None,
    out_dir: Path = OUT_DIR,
    reasoner: Optional[OllamaReasoner] = None,
    rebuild_index: bool = False,
    include_pdfs: bool = True,
    **retriever_kwargs: Any,
) -> Tuple[ConsentSupervisorAgent, Dict[str, Any]]:
    """Arma el agente completo y devuelve también un resumen de la ingesta/indexación."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = mode or os.environ.get("RETRIEVER_MODE", "local")
    if mode == "qdrant":
        retriever_kwargs.setdefault("cache_dir", str(BASE_DIR / ".modelos"))
        retriever_kwargs.setdefault("embedded_fallback", str(BASE_DIR / ".qdrant_local"))
    corpus = build_corpus(include_pdfs)
    governance = GovernanceLog(out_dir / "governance_log.json")
    hitl = HITLQueue(out_dir / "pending_reviews.json", governance, out_dir / "informes_finales.json")
    backend = build_backend(
        mode,
        corpus=corpus,
        analyzer=EvidenceAnalyzer.from_file(CONFIG_DIR / "consent_rules.json"),
        exceptions=ExceptionCatalog.from_file(CONFIG_DIR / "excepciones_art14.json"),
        governance_log=governance,
        **retriever_kwargs,
    )
    index_info = backend.index(rebuild=rebuild_index) if backend.mode == "qdrant" else {
        "backend": backend.mode, "fragments": len(corpus), "reindexed": True}
    agent = ConsentSupervisorAgent(mcp_backend=backend, hitl_queue=hitl, reasoner=reasoner or OllamaReasoner())
    return agent, {"index": index_info, "ingest": corpus.ingest_report,
                   "location": getattr(backend.retriever, "location", "memoria (BM25 en Python)"),
                   "reranker_error": getattr(backend.retriever, "reranker_error", None)}
