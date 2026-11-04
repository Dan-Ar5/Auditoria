from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import dashboard
from agente import OllamaReasoner, build_agent

ROOT = Path(__file__).resolve().parent.parent


def read_case(name: str) -> str:
    return (ROOT / "evidencias" / name).read_text(encoding="utf-8")


@pytest.fixture
def agent(tmp_path):
    return build_agent(mode="local", out_dir=tmp_path, include_pdfs=False, reasoner=OllamaReasoner(enabled=False))[0]


@pytest.fixture
def panel(agent):
    dashboard.STATE.update({"agent": agent, "info": {"modo": "local", "fragmentos": len(agent.mcp.corpus)},
                            "records": {}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.PanelHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def post(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=30)


def test_events_follow_the_pipeline_without_changing_the_result(agent):
    events = []
    with_events = agent.audit_evidence(read_case("caso_tiendaandina.txt"), "t.txt", on_event=events.append)
    without_events = agent.audit_evidence(read_case("caso_tiendaandina.txt"), "t.txt")
    steps = [e["paso"] for e in events]
    assert steps[0] == "entrada" and steps[-1] == "decision"
    assert steps.index("failfast") < steps.index("busqueda") < steps.index("reglas")
    assert [d["dictamen"] for d in with_events["domains"]] == [d["dictamen"] for d in without_events["domains"]]
    assert agent._on_event is None  # el aviso no queda enganchado tras la auditoría


def test_exception_case_marks_consent_domains_as_skipped(agent):
    events = []
    agent.audit_evidence(read_case("caso_banco.txt"), "b.txt", on_event=events.append)
    assert [e["estado"] for e in events if e["paso"] == "dictamen"].count("omitido") == 2


def test_panel_streams_audit_and_handles_auditor_decision(panel):
    with urllib.request.urlopen(panel + "/", timeout=10) as page:
        assert "Supervisor de Consentimientos" in page.read().decode("utf-8")
    casos = json.load(urllib.request.urlopen(panel + "/api/casos", timeout=10))
    assert len(casos) == 5
    lines = [json.loads(line) for line in post(panel + "/api/auditar",
                                               {"texto": read_case("caso_banco.txt"), "nombre": "caso_banco.txt"})]
    assert lines[0]["tipo"] == "evento" and lines[-1]["tipo"] == "resultado"
    record = lines[-1]["registro"]
    assert record["review_status"] == "PENDIENTE_REVISION_AUDITOR"
    report = urllib.request.urlopen(f"{panel}/api/informe?id={record['audit_id']}", timeout=10).read().decode("utf-8")
    assert "Informe de auditoría" in report
    pending = json.load(urllib.request.urlopen(panel + "/api/pendientes", timeout=10))
    decision = json.load(post(panel + "/api/decidir", {"ticket": pending[0]["ticket"], "accion": "aprobar",
                                                       "nota": "Excepción verificada"}))
    assert decision["ok"] and decision["aprobados"] == 1 and decision["pendientes"] == []


def test_panel_rejects_empty_evidence(panel):
    with pytest.raises(urllib.error.HTTPError) as error:
        post(panel + "/api/auditar", {"texto": "   "})
    assert error.value.code == 400
