from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

RE_NEGATION = re.compile(r"\b(no|sin|ning[uú]n[ao]?|ni|nunca|tampoco|carece[n]?|ausencia|falta[n]?)\b", re.IGNORECASE)

# Estados de una regla sobre la evidencia.
CUMPLE = "cumple"
INCUMPLE = "incumple"
NO_EVIDENCIADO = "no_evidenciado"
NO_DETECTADO = "no_detectado"


def _read_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def segments(text: str) -> List[str]:
    """Divide la evidencia en oraciones/líneas para evaluar cada afirmación con su propia negación."""
    return [s.strip(" -•\t") for s in re.split(r"(?<=[.;])\s+|\n", text) if s.strip(" -•\t")]


def find_mentions(text: str, patterns: List[str]) -> Dict[str, List[str]]:
    """Separa las menciones afirmativas de las negadas ('No se indican destinatarios...')."""
    found: Dict[str, List[str]] = {"affirmative": [], "negated": []}
    for segment in segments(text):
        for pattern in patterns:
            match = re.search(pattern, segment, re.IGNORECASE)
            if match:
                kind = "negated" if RE_NEGATION.search(segment[:match.start()]) else "affirmative"
                found[kind].append(segment)
                break
    return found


class EvidenceAnalyzer:
    """Motor de reglas deterministas sobre la evidencia auditada (configurable en consent_rules.json)."""

    def __init__(self, rules: Optional[List[Dict[str, Any]]] = None,
                 injection_patterns: Optional[List[str]] = None) -> None:
        self.rules = rules or []
        self.injection_patterns = injection_patterns or []

    @classmethod
    def from_file(cls, path: str | Path) -> "EvidenceAnalyzer":
        data = _read_json(path)
        return cls(data.get("rules", []), data.get("injection_patterns", []))

    def analyze(self, evidence: str) -> List[Dict[str, Any]]:
        return [self.evaluate_rule(rule, evidence) for rule in self.rules]

    def evaluate_rule(self, rule: Dict[str, Any], evidence: str) -> Dict[str, Any]:
        result = {key: rule.get(key) for key in ("id", "domain", "type", "description", "controls", "articles",
                                                 "finding", "corrective_action", "priority")}
        applies_if = rule.get("applies_if")
        if applies_if and not any(re.search(p, evidence, re.IGNORECASE) for p in applies_if):
            return {**result, "status": NO_DETECTADO, "quote": None, "note": "La regla no aplica al contexto."}

        mentions = find_mentions(evidence, rule.get("patterns", []))
        if rule.get("type") == "prohibido":
            if mentions["affirmative"]:
                return {**result, "status": INCUMPLE, "quote": mentions["affirmative"][0]}
            return {**result, "status": CUMPLE if mentions["negated"] else NO_DETECTADO,
                    "quote": mentions["negated"][0] if mentions["negated"] else None}
        # requerido: debe constar de forma afirmativa en la evidencia
        if mentions["affirmative"]:
            return {**result, "status": CUMPLE, "quote": mentions["affirmative"][0]}
        if mentions["negated"]:
            return {**result, "status": INCUMPLE, "quote": mentions["negated"][0]}
        return {**result, "status": NO_EVIDENCIADO, "quote": None}

    def detect_injection(self, evidence: str) -> List[str]:
        return [s for s in segments(evidence)
                if any(re.search(p, s, re.IGNORECASE) for p in self.injection_patterns)]


class ExceptionCatalog:
    """Excepciones al consentimiento del Art. 14 de la Ley N.° 29733 para el paso Fail-Fast."""

    def __init__(self, exceptions: Optional[List[Dict[str, Any]]] = None,
                 not_covered_patterns: Optional[List[str]] = None, note: str = "") -> None:
        self.exceptions = exceptions or []
        self.not_covered_patterns = not_covered_patterns or []
        self.note = note

    @classmethod
    def from_file(cls, path: str | Path) -> "ExceptionCatalog":
        data = _read_json(path)
        return cls(data.get("exceptions", []), data.get("not_covered_patterns", []), data.get("nota", ""))

    def check(self, evidence: str) -> Dict[str, Any]:
        matched = []
        for exception in self.exceptions:
            mentions = find_mentions(evidence, exception.get("patterns", []))
            if mentions["affirmative"]:
                matched.append({"id": exception["id"], "numeral": exception.get("numeral"),
                                "description": exception["description"], "quote": mentions["affirmative"][0]})

        # La excepción solo cubre el tratamiento necesario para ese fin: no ampara marketing ni perfilamiento.
        blocking = find_mentions(evidence, self.not_covered_patterns)["affirmative"]
        applies = bool(matched) and not blocking
        if applies:
            first = matched[0]
            numeral = f"numeral {first['numeral']}" if first.get("numeral") else "excepción legal"
            justification = (f"Art. 14 ({numeral}): {first['description']} "
                             f"Evidencia: «{first['quote']}».")
        elif matched:
            justification = (f"Hay indicios de la excepción «{matched[0]['description']}», pero la evidencia "
                             f"también declara fines no amparados por ella («{blocking[0]}»); "
                             "el consentimiento sigue siendo exigible para esos fines.")
        else:
            justification = "Ninguna excepción del Art. 14 se ajusta al contexto descrito: el consentimiento es exigible."
        return {"applies": applies, "matched": matched, "blocking_quotes": blocking,
                "justification": justification, "source": "reglas"}
