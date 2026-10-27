from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agente import (
    ConsentSupervisorAgent,
    EvidenceAnalyzer,
    ExceptionCatalog,
    NormativeCorpus,
    OllamaReasoner,
    build_agent,
    build_evidence_matrix,
    export_csv,
    export_json,
    export_markdown,
    fragment_document,
)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
EVIDENCE_DIR = BASE_DIR / "evidencias"


def read_case(name: str) -> str:
    return (EVIDENCE_DIR / name).read_text(encoding="utf-8")


def verdicts(record):
    return {d["domain"].split(".")[0]: d["dictamen"] for d in record["domains"]}


class FakeReasoner(OllamaReasoner):
    """LLM simulado para probar las guardas sin depender de Ollama."""

    def __init__(self, exception=None, domain=None):
        super().__init__(enabled=False)
        self.exception_answer = exception
        self.domain_answer = domain
        self.model = "fake-llm"

    def is_available(self):
        return True

    def check_exception(self, evidence, fragments):
        return self.exception_answer

    def evaluate_domain(self, domain_name, evidence, fragments, rule_findings):
        return self.domain_answer(domain_name, fragments) if callable(self.domain_answer) else self.domain_answer


@pytest.fixture
def make_agent(tmp_path):
    def _make(reasoner=None):
        agent, _ = build_agent(mode="local", out_dir=tmp_path, include_pdfs=False,
                               reasoner=reasoner or OllamaReasoner(enabled=False))
        return agent
    return _make


def test_tiendaandina_matches_tif_report(make_agent):
    record = make_agent().audit_evidence(read_case("caso_tiendaandina.txt"), "caso_tiendaandina.txt")
    assert verdicts(record) == {"1": "No Conforme", "2": "No Conforme", "3": "No Conforme",
                                "4": "Excepción no aplicable"}
    assert record["fail_fast"]["exception_applies"] is False
    assert record["overall_status"] == "NO_CONFORME"
    assert record["corrective_actions"][0].startswith("Dejar la casilla desmarcada")
    assert record["corrective_actions"][-1].startswith("Reauditar en 30 días")


def test_fail_fast_contract_exception_skips_consent_domain(make_agent):
    agent = make_agent()
    record = agent.audit_evidence(read_case("caso_banco.txt"), "caso_banco.txt")
    assert record["fail_fast"]["exception_applies"] is True
    assert verdicts(record)["2"] == "No Aplica"
    assert verdicts(record)["3"] == "No Aplica"
    assert verdicts(record)["1"] == "No Conforme"  # la excepción no exime del deber de información
    assert record["fail_fast"]["fragments"][0] == "LEY-ART14-5"
    assert record["review_status"] == "PENDIENTE_REVISION_AUDITOR"
    assert len(agent.hitl_queue.list_pending()) == 1


def test_exception_does_not_cover_marketing():
    catalog = ExceptionCatalog.from_file(CONFIG_DIR / "excepciones_art14.json")
    result = catalog.check("Formulario para la apertura de cuenta. También enviaremos publicidad y promociones.")
    assert result["matched"] and result["applies"] is False


def test_compliant_case_is_emitted_without_hitl(make_agent):
    agent = make_agent()
    record = agent.audit_evidence(read_case("caso_conforme.txt"), "caso_conforme.txt")
    assert set(verdicts(record).values()) == {"Conforme", "Excepción no aplicable"}
    assert record["review_status"] == "EMITIDO"
    assert agent.mcp.governance_log.entries[-1]["audit_id"] == record["audit_id"]


def test_prompt_injection_goes_to_hitl(make_agent):
    record = make_agent().audit_evidence(read_case("caso_inyeccion.txt"), "caso_inyeccion.txt")
    assert record["injection_suspects"]
    assert record["hitl_trigger"]["requires_auditor_signoff"] is True
    assert verdicts(record)["2"] == "No Conforme"


def test_negation_is_detected():
    analyzer = EvidenceAnalyzer.from_file(CONFIG_DIR / "consent_rules.json")
    findings = {f["id"]: f["status"] for f in analyzer.analyze(
        "No se indican destinatarios ni plazo de conservación. La casilla no está premarcada.")}
    assert findings["INF-03"] == "incumple"
    assert findings["INF-04"] == "incumple"
    assert findings["OBT-02"] == "cumple"


def test_llm_cannot_downgrade_a_violation(make_agent):
    reasoner = FakeReasoner(
        exception={"aplica_excepcion": False, "justificacion": "No aplica.", "confianza": 0.9},
        domain={"exigencia": "x", "evidencia_citada": ["texto inventado que no está"], "brecha": "x",
                "dictamen": "Conforme", "hallazgo": "x", "medida_correctiva": "x",
                "fragmentos_citados": ["ISO-INVENTADO"], "confianza": 0.9},
    )
    record = make_agent(reasoner).audit_evidence(read_case("caso_tiendaandina.txt"), "caso_tiendaandina.txt")
    assert verdicts(record)["2"] == "No Conforme"
    reason = record["hitl_trigger"]["reason"]
    assert "el LLM opina Conforme" in reason and "no aparecen en la evidencia" in reason and "ISO-INVENTADO" in reason


def test_llm_disagreement_on_compliant_case_goes_to_auditor(make_agent):
    reasoner = FakeReasoner(
        exception={"aplica_excepcion": False, "justificacion": "No aplica.", "confianza": 0.9},
        domain={"exigencia": "x", "evidencia_citada": [], "brecha": "Brecha supuesta del LLM",
                "dictamen": "No Conforme", "hallazgo": "x", "medida_correctiva": "x", "confianza": 0.9},
    )
    record = make_agent(reasoner).audit_evidence(read_case("caso_conforme.txt"), "caso_conforme.txt")
    assert verdicts(record)["1"] == "Conforme"
    assert record["domains"][0]["llm_opinion"]["dictamen"] == "No Conforme"
    assert record["review_status"] == "PENDIENTE_REVISION_AUDITOR"


def test_llm_agreement_uses_llm_narrative(make_agent):
    def answer(domain_name, fragments):
        return {"exigencia": "Exigencia del LLM", "brecha": "Brecha del LLM", "dictamen": "No Conforme",
                "evidencia_citada": ["No existe registro de la fecha y hora en que el usuario otorgó el consentimiento."],
                "hallazgo": "Hallazgo del LLM", "medida_correctiva": "Medida del LLM",
                "fragmentos_citados": [fragments[0]["id"]], "confianza": 0.95}

    reasoner = FakeReasoner(exception={"aplica_excepcion": False, "justificacion": "Sin excepción.", "confianza": 0.9},
                            domain=answer)
    record = make_agent(reasoner).audit_evidence(read_case("caso_tiendaandina.txt"), "caso_tiendaandina.txt")
    domain = record["domains"][1]
    assert domain["source"] == "llm+reglas" and domain["hallazgo"] == "Hallazgo del LLM"
    assert record["review_status"] == "EMITIDO"


def test_paraphrased_quote_is_grounded_to_literal_text():
    from agente.agent import _confidence, _ground_quote

    evidence = read_case("caso_conforme.txt")
    literal = _ground_quote("El sitio web ofrece un panel de preferencias para retirar el consentimiento en línea "
                            "y cada boletín incluye un enlace 'Darse de baja'.", evidence)
    assert literal and literal.startswith("Cada boletín incluye un enlace")
    assert _ground_quote("No hay opción de no suscribirse al servicio de mensajería", evidence) is None
    assert _confidence(100) == 1.0 and _confidence("0.8") == 0.8 and _confidence(None) == 0.0


def test_structural_chunking_splits_article_14_by_numeral():
    numerals = "\n".join(f"{i}. Cuando ocurra el supuesto número {i}. " + "Texto del supuesto. " * 15 for i in range(1, 6))
    law = ("Artículo 5. Principio de consentimiento\nPara el tratamiento debe mediar el consentimiento.\n"
           "Artículo 14. Limitaciones al consentimiento\nNo se requiere el consentimiento en los siguientes casos:\n"
           f"{numerals}\nArtículo 18. Derecho de información\nEl titular tiene derecho a ser informado.")
    fragments = fragment_document("Ley_29733.pdf", [law])
    art14 = [f for f in fragments if f["articulo"] == 14]
    assert [f["numeral"] for f in art14] == ["1", "2", "3", "4", "5"]
    assert all(f["texto"].startswith("Artículo 14.") and f["naturaleza"] == "excepcion" for f in art14)
    assert {f["articulo"] for f in fragments} == {5, 14, 18}


def test_corpus_metadata_follows_tif():
    corpus = NormativeCorpus.from_file(CONFIG_DIR / "corpus_normativo.json")
    required = {"norma", "tipo_de_documento", "control", "articulo", "seccion_jerarquica", "naturaleza", "idioma"}
    assert all(required <= set(f) for f in corpus.fragments)
    assert corpus.filter(articulo=14, naturaleza="excepcion")
    assert {"A.1.2.2", "A.1.2.4", "A.1.2.5", "A.1.3.3", "A.1.3.4", "A.1.3.5"} <= {f["control"] for f in corpus.fragments}


def test_hitl_approve_reject_and_consolidate(make_agent, tmp_path):
    agent = make_agent()
    agent.audit_evidence(read_case("caso_banco.txt"), "caso_banco.txt")
    agent.audit_evidence(read_case("caso_inyeccion.txt"), "caso_inyeccion.txt")
    hitl = agent.hitl_queue
    tickets = [item["ticket"] for item in hitl.list_pending()]
    assert hitl.approve(tickets[0], "auditor@empresa.com", "ok") is True
    assert hitl.reject(tickets[1], "auditor@empresa.com", "manipulada") is True
    assert hitl.approve(tickets[0], "auditor@empresa.com", "doble") is False
    assert len(hitl.consolidate()) == 1
    assert (tmp_path / "informes_finales.json").exists()


def test_exports_and_evidence_matrix(make_agent, tmp_path):
    agent = make_agent()
    records = [agent.audit_evidence(read_case("caso_tiendaandina.txt"), "caso_tiendaandina.txt")]
    assert export_json(records, tmp_path / "informes.json").exists()
    assert export_csv(records, tmp_path / "informes.csv").exists()
    assert "Dictamen por dominios" in export_markdown(records[0], tmp_path / "informe.md").read_text(encoding="utf-8")
    matrix = build_evidence_matrix(records, agent.mcp.call_log, agent.hitl_queue.decisions)
    assert any(row["evidence_type"] == "Verificación Fail-Fast" for row in matrix)
    json.dumps(records, ensure_ascii=False)  # el registro estandarizado es serializable


def test_mcp_tools_respond(make_agent):
    backend = make_agent().mcp
    assert backend.mcp_tool_retrieve_norms("revocar consentimiento", filters={"control": ["A.1.3.5"]}).ok
    assert backend.mcp_tool_check_exceptions("lavado de activos").data["applies"] is True
    assert backend.mcp_tool_analyze_evidence("Casilla premarcada").ok
    assert backend.mcp_tool_emit_audit_report({"audit_id": "X"}).ok


def test_create_server_registers_tools():
    import mcp_server

    if mcp_server.FastMCP is None:
        with pytest.raises(RuntimeError):
            mcp_server.create_server()
        return
    names = {tool.name for tool in asyncio.run(mcp_server.create_server().list_tools())}
    assert {"mcp_tool_retrieve_norms", "mcp_tool_check_exceptions", "mcp_tool_analyze_evidence",
            "mcp_tool_emit_audit_report", "mcp_tool_audit_consent"} <= names
