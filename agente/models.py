from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

AGENT_ID = "AGT-CONSENT-01"
NORMA_ISO = "ISO/IEC 27701:2025"
NORMA_LEY = "Ley N.° 29733"
NORMA_REGLAMENTO = "Reglamento Ley N.° 29733 (DS 016-2024-JUS)"

CONFORME = "Conforme"
NO_CONFORME = "No Conforme"
NO_APLICA = "No Aplica"
DICTAMENES = (CONFORME, NO_CONFORME, NO_APLICA)

ESTADO_EMITIDO = "EMITIDO"
ESTADO_PENDIENTE = "PENDIENTE_REVISION_AUDITOR"

# Dominios del reporte (TIF, sección 3.3) con sus controles, artículos y la consulta de recuperación.
DOMAINS: Dict[str, Dict[str, Any]] = {
    "informacion": {
        "name": "1. Deber de información y propósito",
        "controls": ["A.1.2.2", "A.1.3.3", "A.1.3.4"],
        "articles": [18],
        "query": "finalidad específica del tratamiento, información previa, clara y accesible al titular, "
                 "destinatarios, plazo de conservación, identidad del responsable",
    },
    "obtencion": {
        "name": "2. Obtención y registro del consentimiento",
        "controls": ["A.1.2.4", "A.1.2.5"],
        "articles": [5],
        "query": "obtener y registrar el consentimiento libre, previo, expreso, inequívoco e informado; "
                 "casilla premarcada; prueba del consentimiento",
    },
    "revocacion": {
        "name": "3. Modificación y revocación",
        "controls": ["A.1.3.5"],
        "articles": [5],
        "query": "mecanismo para modificar o retirar el consentimiento en cualquier momento, "
                 "por el mismo canal en que se obtuvo",
    },
}
EXCEPTIONS_DOMAIN = "4. Excepciones legales"
CONTROLS = tuple(c for d in DOMAINS.values() for c in d["controls"])


@dataclass
class MCPResponse:
    tool: str
    ok: bool
    data: Any
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"tool": self.tool, "ok": self.ok, "data": self.data, "error": self.error}
