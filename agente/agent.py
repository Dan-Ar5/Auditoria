from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .backends import ConsentMCPBackend
from .evidence import INCUMPLE, NO_EVIDENCIADO, segments
from .hitl import HITLQueue
from .models import (AGENT_ID, CONFORME, DICTAMENES, DOMAINS, ESTADO_EMITIDO, ESTADO_PENDIENTE,
                     EXCEPTIONS_DOMAIN, NO_APLICA, NO_CONFORME, NORMA_ISO, NORMA_LEY, NORMA_REGLAMENTO)
from .reasoner import OllamaReasoner
from .retrieval import _tokens

MIN_LLM_CONFIDENCE = 0.5   # la autoevaluación de modelos pequeños es poco fiable: solo alerta si es muy baja
QUOTE_OVERLAP = 0.85       # proporción de palabras de la cita que deben estar en la evidencia
MIN_QUOTE_WORDS = 3        # una "cita" de una o dos palabras no prueba nada
CONSENT_DOMAINS = ("obtencion", "revocacion")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[«»“”\"'‘’]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _ground_quote(quote: str, evidence: str) -> Optional[str]:
    """Devuelve la oración ORIGINAL de la evidencia que respalda una cita del LLM, o None si es inventada.

    Los modelos pequeños parafrasean levemente; se acepta la cita si casi todas sus palabras
    están en la evidencia, y se reemplaza por el texto literal de la evidencia.
    """
    words = set(_tokens(quote))
    if len(words) < MIN_QUOTE_WORDS:
        return None
    if _normalize(quote) in _normalize(evidence):
        exact = True
    else:
        exact = len(words & set(_tokens(evidence))) / len(words) >= QUOTE_OVERLAP
    if not exact:
        return None
    best = max(segments(evidence), key=lambda s: len(words & set(_tokens(s))), default=None)
    return best


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(number / 100 if number > 1 else number, 0.0), 1.0)


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?\.)(\s|$)", text.strip())
    return match.group(1) if match else text.strip()


class ConsentSupervisorAgent:
    """Agente AGT-CONSENT-01: audita el ciclo de vida del consentimiento (TIF, RAG híbrido + Fail-Fast)."""

    def __init__(self, mcp_backend: ConsentMCPBackend, hitl_queue: HITLQueue,
                 reasoner: Optional[OllamaReasoner] = None, fragments_per_domain: int = 4) -> None:
        self.mcp = mcp_backend
        self.hitl_queue = hitl_queue
        self.reasoner = reasoner or OllamaReasoner()
        self.fragments_per_domain = fragments_per_domain

    # ------------------------------------------------------------------ flujo principal
    def audit_evidence(self, evidence_text: str, evidence_name: str = "evidencia.txt") -> Dict[str, Any]:
        evidence_text = evidence_text.strip()
        analysis = self.mcp.mcp_tool_analyze_evidence(evidence_text).data
        findings = analysis["findings"]
        hitl_reasons: List[str] = []
        if analysis["injection_suspects"]:
            hitl_reasons.append("Posible inyección de instrucciones en la evidencia: "
                                f"«{analysis['injection_suspects'][0]}».")

        # Paso 1 (Fail-Fast): excepciones del Art. 14 antes de cualquier control de consentimiento.
        fail_fast = self._fail_fast(evidence_text, hitl_reasons)

        # Pasos 2-4: recuperación híbrida y evaluación por dominio.
        domains = []
        for key, domain in DOMAINS.items():
            # La excepción exime del consentimiento (obtenerlo y retirarlo), no del deber de información.
            if key in CONSENT_DOMAINS and fail_fast["exception_applies"]:
                domains.append(self._not_applicable_domain(domain, fail_fast))
                continue
            domain_findings = [f for f in findings if f["domain"] == key]
            domains.append(self._evaluate_domain(key, domain, evidence_text, domain_findings, hitl_reasons))
        domains.append(self._exceptions_row(fail_fast))

        record = self._build_record(evidence_text, evidence_name, fail_fast, domains, findings,
                                    analysis["injection_suspects"], hitl_reasons)
        if record["hitl_trigger"]["requires_auditor_signoff"]:
            record["hitl_trigger"]["ticket"] = self.hitl_queue.send_for_review(record)
        else:
            self.mcp.mcp_tool_emit_audit_report(record)
        return record

    # ------------------------------------------------------------------ Fail-Fast
    def _fail_fast(self, evidence: str, hitl_reasons: List[str]) -> Dict[str, Any]:
        rules = self.mcp.mcp_tool_check_exceptions(evidence).data
        fragments = rules["fragments"]
        result = {"exception_applies": rules["applies"], "justification": rules["justification"],
                  "matched": rules["matched"], "source": "reglas",
                  "fragments": [f["id"] for f in fragments], "fragment_details": fragments}

        llm = self.reasoner.check_exception(evidence, fragments) if fragments else None
        if llm is not None:
            llm_applies = bool(llm.get("aplica_excepcion"))
            result.update({"source": "llm", "llm_justification": llm.get("justificacion"),
                           "llm_purpose": llm.get("finalidad_del_tratamiento"),
                           "llm_confidence": _confidence(llm.get("confianza"))})
            if llm_applies != rules["applies"]:
                hitl_reasons.append("Discrepancia en el paso Fail-Fast entre el LLM "
                                    f"({'aplica' if llm_applies else 'no aplica'}) y las reglas "
                                    f"({'aplica' if rules['applies'] else 'no aplica'}).")
                # Ante la duda se audita todo: la excepción solo se aplica si ambos coinciden.
                result["exception_applies"] = False
                result["justification"] = (f"{rules['justification']} (El LLM opinó distinto; se mantiene la "
                                           "evaluación completa hasta la revisión del auditor.)")
            elif llm.get("justificacion"):
                result["justification"] = llm["justificacion"]
        if result["exception_applies"]:
            hitl_reasons.append("Se aplicó una excepción del Art. 14: el dictamen de inaplicabilidad "
                                "requiere confirmación del auditor.")
        return result

    # ------------------------------------------------------------------ dominios
    def _retrieve_domain_context(self, key: str, domain: Dict[str, Any], evidence: str) -> List[Dict[str, Any]]:
        query = f"{domain['query']}. {evidence[:600]}"
        iso_controls = domain["controls"] + [c.replace("A.", "B.", 1) for c in domain["controls"]]
        articles = domain["articles"] + ([13] if key == "obtencion" else [])
        searches = [
            {"norma": NORMA_ISO, "control": iso_controls},
            {"norma": [NORMA_LEY, NORMA_REGLAMENTO], "articulo": articles},
        ]
        fragments: List[Dict[str, Any]] = []
        seen = set()
        for filters in searches:
            response = self.mcp.mcp_tool_retrieve_norms(query, top_k=self.fragments_per_domain, filters=filters)
            for fragment in (response.data or {}).get("results", []) if response.ok else []:
                if fragment["id"] not in seen:
                    seen.add(fragment["id"])
                    fragments.append(fragment)
        return fragments

    def _evaluate_domain(self, key: str, domain: Dict[str, Any], evidence: str,
                         findings: List[Dict[str, Any]], hitl_reasons: List[str]) -> Dict[str, Any]:
        fragments = self._retrieve_domain_context(key, domain, evidence)
        failing = [f for f in findings if f["status"] in (INCUMPLE, NO_EVIDENCIADO)]
        rules_dictamen = NO_CONFORME if failing else CONFORME

        result = {
            "domain": domain["name"],
            "controls": domain["controls"],
            "articles": domain["articles"],
            "exigencia": " ".join(_first_sentence(f["texto"]) for f in fragments[:3]),
            "evidencia_citada": list(dict.fromkeys(f["quote"] for f in findings if f.get("quote"))),
            "brecha": "; ".join(f"{f['description']}: {f['status'].replace('_', ' ')}" for f in failing)
                      or "Sin brechas detectadas.",
            "dictamen": rules_dictamen,
            "hallazgo": " ".join(f["finding"] for f in failing) or "La evidencia cumple los requisitos evaluados.",
            "medida_correctiva": " ".join(f["corrective_action"] for f in failing) or "Ninguna.",
            "rule_findings": [{k: f[k] for k in ("id", "description", "status", "quote")} for f in findings],
            "fragments": [f["id"] for f in fragments],
            "fragment_details": fragments,
            "source": "reglas",
            "confidence": 0.9 if not any(f["status"] == NO_EVIDENCIADO for f in findings) else 0.7,
        }

        llm = self.reasoner.evaluate_domain(domain["name"], evidence, fragments, findings) if fragments else None
        if llm is None:
            return result
        result.update({"source": "llm+reglas", "llm_reasoning": {k: llm.get(k) for k in ("exigencia", "brecha")}})
        llm_dictamen = llm.get("dictamen")
        confidence = _confidence(llm.get("confianza"))

        # Guardas anti-alucinación: citas respaldadas por la evidencia y fragmentos realmente recuperados.
        raw_quotes = [q for q in llm.get("evidencia_citada") or [] if isinstance(q, str) and q.strip()]
        grounded = [_ground_quote(q, evidence) for q in raw_quotes]
        quotes = list(dict.fromkeys(q for q in grounded if q))
        invented_quotes = grounded.count(None)
        retrieved_ids = {f["id"] for f in fragments}
        cited_refs = [str(r).strip(" []()") for r in llm.get("fragmentos_citados") or []]
        invented_refs = [r for r in cited_refs if r and r not in retrieved_ids]
        if invented_quotes:
            hitl_reasons.append(f"{domain['name']}: el LLM citó {invented_quotes} texto(s) que no aparecen en la evidencia.")
        if invented_refs:
            hitl_reasons.append(f"{domain['name']}: el LLM citó fragmentos no recuperados ({', '.join(invented_refs)}).")

        if llm_dictamen not in DICTAMENES or llm_dictamen == NO_APLICA:
            hitl_reasons.append(f"{domain['name']}: dictamen del LLM no válido para este dominio ({llm_dictamen}).")
            return result
        if llm_dictamen != rules_dictamen:
            # El dictamen provisional es el de las reglas (verificable regla por regla); la opinión del LLM
            # se adjunta y el informe queda retenido hasta que el auditor decida.
            hitl_reasons.append(f"{domain['name']}: el LLM opina {llm_dictamen} y las reglas {rules_dictamen}; "
                                "se mantiene el dictamen de las reglas hasta la revisión del auditor.")
            result["llm_opinion"] = {"dictamen": llm_dictamen, "brecha": llm.get("brecha"),
                                     "hallazgo": llm.get("hallazgo"), "evidencia_citada": quotes}
            result["confidence"] = min(result["confidence"], 0.5)
            return result
        if confidence < MIN_LLM_CONFIDENCE:
            hitl_reasons.append(f"{domain['name']}: confianza del LLM baja ({confidence:.2f}).")
        result.update({
            "exigencia": llm.get("exigencia") or result["exigencia"],
            "evidencia_citada": quotes or result["evidencia_citada"],
            "brecha": llm.get("brecha") or result["brecha"],
            "hallazgo": llm.get("hallazgo") or result["hallazgo"],
            "medida_correctiva": llm.get("medida_correctiva") or result["medida_correctiva"],
            "confidence": round(confidence, 2),
        })
        return result

    @staticmethod
    def _not_applicable_domain(domain: Dict[str, Any], fail_fast: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "domain": domain["name"], "controls": domain["controls"], "articles": domain["articles"],
            "exigencia": "No evaluada: el paso Fail-Fast identificó una excepción al consentimiento.",
            "evidencia_citada": [m["quote"] for m in fail_fast["matched"]],
            "brecha": "No aplica.", "dictamen": NO_APLICA,
            "hallazgo": f"Excepción al consentimiento: {fail_fast['justification']}",
            "medida_correctiva": "Ninguna sobre el consentimiento; se mantienen el deber de información y la finalidad.",
            "rule_findings": [], "fragments": fail_fast["fragments"], "fragment_details": [],
            "source": fail_fast["source"], "confidence": 0.8,
        }

    @staticmethod
    def _exceptions_row(fail_fast: Dict[str, Any]) -> Dict[str, Any]:
        applies = fail_fast["exception_applies"]
        return {
            "domain": EXCEPTIONS_DOMAIN, "controls": [], "articles": [14],
            "exigencia": "Art. 14: supuestos en que no se requiere el consentimiento del titular.",
            "evidencia_citada": [m["quote"] for m in fail_fast["matched"]],
            "brecha": "No aplica.",
            "dictamen": "Excepción aplicable" if applies else "Excepción no aplicable",
            "hallazgo": fail_fast["justification"],
            "medida_correctiva": ("Confirmar que el tratamiento se limita a la finalidad amparada por la excepción."
                                  if applies else "Ninguna; se mantiene la evaluación de los dominios 1 a 3."),
            "rule_findings": [], "fragments": fail_fast["fragments"], "fragment_details": fail_fast["fragment_details"],
            "source": fail_fast["source"], "confidence": None,
        }

    # ------------------------------------------------------------------ registro estandarizado
    def _build_record(self, evidence: str, evidence_name: str, fail_fast: Dict[str, Any],
                      domains: List[Dict[str, Any]], findings: List[Dict[str, Any]],
                      injection_suspects: List[str], hitl_reasons: List[str]) -> Dict[str, Any]:
        organization = self._field(evidence, "Empresa") or evidence_name
        failing = sorted((f for f in findings if f["status"] in (INCUMPLE, NO_EVIDENCIADO)
                          and not (fail_fast["exception_applies"] and f["domain"] in CONSENT_DOMAINS)),
                         key=lambda f: f.get("priority") or 99)
        actions: List[str] = []
        for finding in failing:
            if finding["corrective_action"] not in actions:
                actions.append(finding["corrective_action"])
        evaluated = [d for d in domains if d["dictamen"] in DICTAMENES]
        overall = NO_CONFORME if any(d["dictamen"] == NO_CONFORME for d in evaluated) else CONFORME
        if overall == NO_CONFORME:
            actions.append("Reauditar en 30 días tras aplicar las medidas.")

        requires_review = bool(hitl_reasons)
        traceability = []
        for domain in domains:
            for fragment in domain["fragment_details"]:
                traceability.append({
                    "domain": domain["domain"], "fragment_id": fragment["id"], "norma": fragment["norma"],
                    "control": fragment.get("control"), "articulo": fragment.get("articulo"),
                    "numeral": fragment.get("numeral"), "naturaleza": fragment.get("naturaleza"),
                    "seccion_jerarquica": fragment.get("seccion_jerarquica"), "tipo_texto": fragment.get("tipo_texto"),
                    "origen": fragment.get("origen"), "pagina": fragment.get("pagina"),
                    "score": fragment.get("score"), "retrieval": fragment.get("retrieval"),
                })

        return {
            "audit_id": self._audit_id(organization),
            "agent_id": AGENT_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject": {
                "organization": organization,
                "scope": self._field(evidence, "Alcance") or "No declarado",
                "evidence_file": evidence_name,
                "evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            },
            "framework": [NORMA_ISO, NORMA_LEY],
            "engine": {"retriever": self.mcp.mode, "llm": self.reasoner.model if self.reasoner.is_available()
                       else "no disponible (fallback determinista)", "temperature": 0.0},
            "fail_fast": {k: fail_fast[k] for k in ("exception_applies", "justification", "matched", "source", "fragments")},
            "domains": [{k: v for k, v in d.items() if k != "fragment_details"} for d in domains],
            "overall_status": "NO_CONFORME" if overall == NO_CONFORME else "CONFORME",
            "corrective_actions": actions,
            "injection_suspects": injection_suspects,
            "review_status": ESTADO_PENDIENTE if requires_review else ESTADO_EMITIDO,
            "hitl_trigger": {
                "requires_auditor_signoff": requires_review,
                "reason": " ".join(hitl_reasons) if hitl_reasons
                          else "Sin observaciones: dictamen consistente entre reglas y recuperación normativa.",
            },
            "traceability": traceability,
            "evidence_text": evidence,
        }

    @staticmethod
    def _field(evidence: str, name: str) -> Optional[str]:
        match = re.search(rf"(?mi)^\s*{name}\s*:\s*(.+)$", evidence)
        return match.group(1).strip() if match else None

    @staticmethod
    def _audit_id(organization: str) -> str:
        text = unicodedata.normalize("NFKD", organization)
        slug = re.sub(r"[^A-Za-z0-9]", "", text)[:6].upper() or "CASO"
        return f"CON-{datetime.now(timezone.utc).strftime('%Y')}-{slug}"
