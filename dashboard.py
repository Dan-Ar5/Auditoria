"""
Panel web local del Supervisor de Consentimientos (AGT-CONSENT-01).

Muestra en el navegador el proceso de auditoría paso a paso, el resultado por dominio
y la cola del auditor (aprobar / rechazar). Solo usa la biblioteca estándar de Python.

Uso:
  python dashboard.py                    # modo local (reglas + BM25) y Llama 3 si Ollama está abierto
  python dashboard.py --modo qdrant      # búsqueda híbrida completa (densa + BM25 -> RRF -> Cross-Encoder)
  python dashboard.py --sin-llm          # sin Ollama: dictamen determinista de las reglas (más rápido)
  python dashboard.py --conservar        # mantiene la cola del auditor de sesiones anteriores
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from agente import OllamaReasoner, build_agent, render_markdown

BASE_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = BASE_DIR / "evidencias"
PANEL_HTML = BASE_DIR / "panel" / "index.html"
OUT_DIR = BASE_DIR / "out" / "panel"
MAX_EVIDENCE_CHARS = 200_000

STATE: Dict[str, Any] = {"agent": None, "info": {}, "records": {}, "lock": threading.Lock()}


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "AGT-CONSENT-01-Panel"

    # ------------------------------------------------------------------ utilidades
    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_EVIDENCE_CHARS * 4:
            raise ValueError("La solicitud es demasiado grande.")
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - firma de la clase base
        pass  # la consola queda limpia; el progreso se ve en el panel

    # ------------------------------------------------------------------ rutas
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = PANEL_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/estado":
            agent = STATE["agent"]
            self._json({**STATE["info"], "llm": agent.reasoner.model if agent.reasoner.is_available() else None,
                        "pendientes": len(agent.hitl_queue.list_pending())})
        elif url.path == "/api/casos":
            self._json([{"nombre": f.name, "texto": f.read_text(encoding="utf-8")}
                        for f in sorted(EVIDENCE_DIR.glob("*.txt"))])
        elif url.path == "/api/pendientes":
            self._json(self._pending())
        elif url.path == "/api/informe":
            audit_id = parse_qs(url.query).get("id", [""])[0]
            record = STATE["records"].get(audit_id)
            if not record:
                self._json({"error": "Informe no encontrado en esta sesión."}, 404)
                return
            body = render_markdown(record).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="informe_{audit_id}.md"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "Ruta no encontrada."}, 404)

    def do_POST(self) -> None:  # noqa: N802
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
            return
        if self.path == "/api/auditar":
            self._audit(data)
        elif self.path == "/api/decidir":
            self._decide(data)
        else:
            self._json({"error": "Ruta no encontrada."}, 404)

    # ------------------------------------------------------------------ auditoría en vivo
    def _audit(self, data: Dict[str, Any]) -> None:
        text = str(data.get("texto") or "").strip()
        name = str(data.get("nombre") or "evidencia_panel.txt")[:120]
        if not text:
            self._json({"error": "Pega o elige una evidencia antes de auditar."}, 400)
            return
        if len(text) > MAX_EVIDENCE_CHARS:
            self._json({"error": "La evidencia es demasiado larga para el panel."}, 400)
            return
        if not STATE["lock"].acquire(blocking=False):
            self._json({"error": "Ya hay una auditoría en curso; espera a que termine."}, 409)
            return
        try:
            # Respuesta en streaming: una línea JSON por cada paso del agente.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            def send(payload: Dict[str, Any]) -> None:
                self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()

            try:
                record = STATE["agent"].audit_evidence(text, name, on_event=lambda e: send({"tipo": "evento", **e}))
                STATE["records"][record["audit_id"]] = record
                send({"tipo": "resultado", "registro": record})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:  # noqa: BLE001 - se informa al panel en lugar de cortar la conexión
                send({"tipo": "error", "mensaje": f"{type(exc).__name__}: {exc}"})
        finally:
            STATE["lock"].release()
            self.close_connection = True

    # ------------------------------------------------------------------ cola del auditor
    @staticmethod
    def _pending():
        return [{
            "ticket": item["ticket"],
            "audit_id": item["record"]["audit_id"],
            "organizacion": item["record"]["subject"]["organization"],
            "resultado": item["record"]["overall_status"],
            "motivo": item["record"]["hitl_trigger"]["reason"],
            "creado": item["created_at"],
        } for item in STATE["agent"].hitl_queue.list_pending()]

    def _decide(self, data: Dict[str, Any]) -> None:
        hitl = STATE["agent"].hitl_queue
        ticket = str(data.get("ticket") or "")
        approver = str(data.get("auditor") or "auditor@panel").strip()[:120]
        note = str(data.get("nota") or "").strip()[:500]
        action = data.get("accion")
        if action not in ("aprobar", "rechazar"):
            self._json({"error": "Acción no válida."}, 400)
            return
        ok = (hitl.approve if action == "aprobar" else hitl.reject)(ticket, approver, note)
        if not ok:
            self._json({"error": "El ticket no existe o ya fue decidido."}, 409)
            return
        approved = hitl.consolidate()
        self._json({"ok": True, "aprobados": len(approved), "pendientes": self._pending()})


def main() -> None:
    parser = argparse.ArgumentParser(description="Panel web del Supervisor de Consentimientos")
    parser.add_argument("--modo", choices=["local", "qdrant"], default="local")
    parser.add_argument("--sin-llm", action="store_true", help="no usar Ollama (dictamen determinista)")
    parser.add_argument("--puerto", type=int, default=8765)
    parser.add_argument("--conservar", action="store_true", help="mantener la cola de sesiones anteriores")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.conservar:
        for stale in ("pending_reviews.json", "governance_log.json", "informes_finales.json"):
            (OUT_DIR / stale).unlink(missing_ok=True)

    print("Preparando el agente (la primera vez en modo qdrant puede tardar)...")
    reasoner = OllamaReasoner(enabled=not args.sin_llm)
    try:
        agent, info = build_agent(mode=args.modo, out_dir=OUT_DIR, reasoner=reasoner)
    except Exception as exc:  # noqa: BLE001 - Qdrant o dependencias no disponibles
        if args.modo != "qdrant":
            raise
        print(f"[!] No se pudo usar Qdrant ({exc}). Se continúa en modo local.")
        agent, info = build_agent(mode="local", out_dir=OUT_DIR, reasoner=reasoner)
    STATE["agent"] = agent
    STATE["info"] = {"modo": agent.mcp.mode, "ubicacion": str(info.get("location")),
                     "fragmentos": len(agent.mcp.corpus), "agente": "AGT-CONSENT-01",
                     "reranker": not info.get("reranker_error") and agent.mcp.mode == "qdrant"}

    server = ThreadingHTTPServer(("127.0.0.1", args.puerto), PanelHandler)
    url = f"http://127.0.0.1:{args.puerto}"
    print(f"Panel listo en {url}  (modo {agent.mcp.mode}, IA: "
          f"{agent.reasoner.model if agent.reasoner.is_available() else 'no disponible'})")
    print("Ctrl+C para detenerlo.")
    if not args.no_abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPanel detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
