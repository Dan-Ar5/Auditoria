from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ESTADO_PENDIENTE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernanceLog:
    """Bitácora de gobernanza persistida en disco (informes emitidos)."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else None
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def append(self, record: Dict[str, Any]) -> None:
        self.entries.append(record)
        self._save()

    def _load(self) -> None:
        if self.path and self.path.exists():
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self.entries, indent=2, ensure_ascii=False), encoding="utf-8")


class HITLQueue:
    """Cola persistente de revisión humana (auditor líder / DPO) para dictámenes que no se emiten solos."""

    def __init__(
        self,
        path: Optional[str | Path] = None,
        governance: Optional[GovernanceLog] = None,
        final_path: Optional[str | Path] = None,
    ) -> None:
        self.path = Path(path) if path else None
        self.final_path = Path(final_path) if final_path else None
        self.governance = governance or GovernanceLog()
        self.pending: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self._load()

    def send_for_review(self, record: Dict[str, Any]) -> str:
        ticket = f"HITL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(self.pending) + 1:03d}"
        self.pending.append({
            "ticket": ticket,
            "record": record,
            "status": ESTADO_PENDIENTE,
            "created_at": _now(),
            "decision": None,
        })
        self._save()
        return ticket

    def _find(self, ticket: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self.pending if item["ticket"] == ticket), None)

    def approve(self, ticket: str, approver: str, note: str = "") -> bool:
        return self._decide(ticket, approver, "APROBADO", note)

    def reject(self, ticket: str, approver: str, note: str = "") -> bool:
        return self._decide(ticket, approver, "RECHAZADO", note)

    def _decide(self, ticket: str, approver: str, status: str, note: str) -> bool:
        item = self._find(ticket)
        if item is None or item["status"] != ESTADO_PENDIENTE:
            return False
        decision = {"status": status, "approver": approver, "note": note, "decided_at": _now()}
        item["status"] = status
        item["decision"] = decision
        item["record"]["review_status"] = status
        self.decisions.append({"ticket": ticket, "audit_id": item["record"].get("audit_id"), **decision})
        self._save()
        return True

    def list_pending(self) -> List[Dict[str, Any]]:
        return [item for item in self.pending if item["status"] == ESTADO_PENDIENTE]

    def consolidate(self) -> List[Dict[str, Any]]:
        """Los informes aprobados por el auditor pasan a la bitácora y a informes_finales.json."""
        approved = [item["record"] for item in self.pending if item["status"] == "APROBADO"]
        logged = {entry.get("audit_id") for entry in self.governance.entries}
        for record in approved:
            if record.get("audit_id") not in logged:
                self.governance.append(record)
        if self.final_path:
            self.final_path.write_text(json.dumps(approved, indent=2, ensure_ascii=False), encoding="utf-8")
        return approved

    def _load(self) -> None:
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.pending = data.get("pending", [])
            self.decisions = data.get("decisions", [])

    def _save(self) -> None:
        if self.path:
            payload = {"pending": self.pending, "decisions": self.decisions}
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
