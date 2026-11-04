"""Informe de auditoría en PDF: HTML con diseño de documento A4, impreso con Edge o Chrome sin interfaz."""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import EXCEPTIONS_DOMAIN

SHORT = {
    "1. Deber de información y propósito": "Deber de información y propósito",
    "2. Obtención y registro del consentimiento": "Obtención y registro del consentimiento",
    "3. Modificación y revocación": "Modificación y revocación del consentimiento",
    EXCEPTIONS_DOMAIN: "Excepciones legales (Art. 14)",
}
REASON_TAGS = [
    ("excepción del Art. 14", "Excepción legal aplicada"), ("faltan datos", "Faltan datos o evidencias"),
    ("contradictori", "Afirmaciones contradictorias"), ("inyección", "Posible manipulación del documento"),
    ("LLM opina", "La IA discrepó de las reglas"), ("ninguna cita", "Citas de la IA no verificables"),
    ("contexto normativo", "Contexto normativo insuficiente"), ("confianza", "Baja confianza de la IA"),
]

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #2B3443; font-size: 10.5pt; line-height: 1.45; margin: 0; }
.band { background: #17223B; color: #F4F5F2; padding: 16px 20px; border-radius: 6px; display: flex; justify-content: space-between; align-items: flex-end; }
.band h1 { margin: 0; font-size: 17pt; font-weight: 600; }
.band .sub { color: #B9C3D3; font-size: 9.5pt; margin-top: 3px; }
.band .id { text-align: right; font-size: 9pt; color: #CBD3DF; }
.verdict { margin: 14px 0 12px; padding: 14px 18px; border-radius: 6px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.verdict.bad { background: #FBEBDF; border-left: 6px solid #B4501A; }
.verdict.ok { background: #E6F2EA; border-left: 6px solid #2F7A4D; }
.verdict .big { font-size: 18pt; font-weight: 700; color: #17223B; }
.chip { display: inline-block; border-radius: 99px; padding: 2px 10px; font-size: 8.5pt; font-weight: 600; white-space: nowrap; }
.chip.hum { background: #EFE9F7; color: #5B3F8E; } .chip.ok { background: #DCEEE2; color: #2F7A4D; }
.chip.bad { background: #F6DCCB; color: #9A4515; } .chip.na { background: #EEF0F3; color: #6E7887; }
table { width: 100%; border-collapse: collapse; }
.facts td { padding: 5px 8px; border-bottom: 1px solid #E5E8EC; font-size: 9.5pt; vertical-align: top; }
.facts td:first-child { width: 28%; color: #6E7887; }
h2 { font-size: 12.5pt; color: #17223B; margin: 18px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #17223B; break-after: avoid; page-break-after: avoid; }
.summary td:last-child { width: 1%; white-space: nowrap; }
.summary td, .summary th { padding: 7px 9px; border: 1px solid #E1E4E8; font-size: 9.5pt; text-align: left; }
.summary th { background: #F3F4F1; color: #17223B; font-weight: 600; }
.dom { border: 1px solid #E1E4E8; border-radius: 6px; padding: 12px 14px; margin-bottom: 10px; page-break-inside: avoid; }
.dom .hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.dom .hd b { font-size: 11pt; color: #17223B; }
.dom .norm { font-size: 8.5pt; color: #6E7887; margin-bottom: 6px; }
.dom p { margin: 5px 0; }
.lbl { font-weight: 600; color: #17223B; }
.quote { border-left: 3px solid #D9692A; background: #FFF7F1; padding: 5px 9px; margin: 4px 0; font-style: italic; font-size: 9.5pt; }
.frags { font-size: 8.5pt; color: #6E7887; }
ol.fix { margin: 4px 0 0; padding-left: 20px; } ol.fix li { margin-bottom: 3px; }
.review { border: 1px solid #DCCFEF; background: #FAF7FD; border-radius: 6px; padding: 10px 14px; }
.review ul { margin: 6px 0 0; padding-left: 18px; }
.sign { display: flex; gap: 40px; margin-top: 26px; }
.sign div { flex: 1; border-top: 1px solid #8A93A1; padding-top: 5px; font-size: 9pt; color: #6E7887; }
.trace td, .trace th { padding: 4px 7px; border-bottom: 1px solid #E5E8EC; font-size: 8.5pt; text-align: left; }
.trace th { color: #6E7887; font-weight: 600; }
pre { white-space: pre-wrap; font-family: Consolas, monospace; font-size: 8.5pt; background: #F6F7F5; border: 1px solid #E5E8EC; border-radius: 6px; padding: 10px; }
.foot { margin-top: 18px; font-size: 8pt; color: #8A93A1; text-align: center; }
.print { position: fixed; top: 14px; right: 14px; background: #D9692A; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; font: inherit; font-weight: 600; cursor: pointer; }
@media print { .print { display: none; } }
"""


def _e(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def _chip(verdict: str) -> str:
    cls = {"Conforme": "ok", "No Conforme": "bad", "No Aplica": "na"}.get(verdict, "na")
    label = {"No Conforme": "No conforme", "No Aplica": "No aplica"}.get(verdict, verdict)
    return f'<span class="chip {cls}">{_e(label)}</span>'


def _reasons(record: Dict[str, Any]) -> List[str]:
    reason = record["hitl_trigger"]["reason"]
    return [label for key, label in REASON_TAGS if key.lower() in reason.lower()]


def render_html(record: Dict[str, Any], print_button: bool = False) -> str:
    """Informe de auditoría como documento HTML listo para imprimir en A4."""
    subject, fail_fast = record["subject"], record["fail_fast"]
    ok = record["overall_status"] == "CONFORME"
    pending = record["review_status"] not in ("EMITIDO", "APROBADO")
    status = {"EMITIDO": "Emitido", "APROBADO": "Aprobado por el auditor", "RECHAZADO": "Rechazado por el auditor"}.get(
        record["review_status"], "Pendiente de revisión del auditor")
    org = subject["organization"].split(" (")[0]
    when = record.get("generated_at", "")
    try:
        when = datetime.fromisoformat(when).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        pass
    domains = [d for d in record["domains"] if d["domain"] != EXCEPTIONS_DOMAIN]

    parts: List[str] = [f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Informe {_e(record['audit_id'])}</title><style>{CSS}</style></head><body>"""]
    if print_button:
        parts.append('<button class="print" onclick="window.print()">Guardar como PDF</button>')
    parts.append(f"""
<div class="band"><div><h1>Informe de auditoría de consentimiento</h1>
<div class="sub">ISO/IEC 27701:2025 · Ley N.° 29733 · Agente {_e(record['agent_id'])}</div></div>
<div class="id">{_e(record['audit_id'])}<br>{_e(when)}</div></div>
<div class="verdict {'ok' if ok else 'bad'}"><span class="big">{'Conforme' if ok else 'No conforme'}</span>
<span class="chip {'hum' if pending else 'ok'}">{_e(status)}</span>
{''.join(f'<span class="chip hum">{_e(r)}</span>' for r in (_reasons(record) if pending else []))}</div>
<table class="facts">
<tr><td>Organización</td><td><b>{_e(org)}</b></td></tr>
<tr><td>Alcance</td><td>{_e(subject['scope'])}</td></tr>
<tr><td>Evidencia</td><td>{_e(subject['evidence_file'])}</td></tr>
<tr><td>Huella SHA-256</td><td style="font-family:Consolas,monospace;font-size:8pt">{_e(subject['evidence_sha256'])}</td></tr>
<tr><td>Motor</td><td>Recuperación {_e(record['engine']['retriever'])} · IA {_e(record['engine']['llm'])} · temperatura {_e(record['engine']['temperature'])}</td></tr>
{f"<tr><td>Ticket de revisión</td><td>{_e(record['hitl_trigger']['ticket'])}</td></tr>" if record['hitl_trigger'].get('ticket') else ''}
</table>

<h2>Resumen del dictamen</h2>
<table class="summary"><tr><th>Dominio</th><th>Normas</th><th>Dictamen</th></tr>""")
    for d in domains:
        norms = " · ".join(filter(None, [
            "ISO 27701 " + ", ".join(d.get("controls", [])) if d.get("controls") else "",
            "Ley 29733 Art. " + ", ".join(map(str, d.get("articles", []))) if d.get("articles") else ""]))
        parts.append(f"<tr><td>{_e(SHORT.get(d['domain'], d['domain']))}</td><td>{_e(norms)}</td><td>{_chip(d['dictamen'])}</td></tr>")
    parts.append(f"""<tr><td>Excepciones legales (Art. 14)</td><td>Ley 29733 Art. 14</td>
<td><span class="chip {'hum' if fail_fast['exception_applies'] else 'na'}">{'Aplica una excepción' if fail_fast['exception_applies'] else 'No aplica'}</span></td></tr></table>
<p style="font-size:9.5pt;margin-top:6px"><span class="lbl">Verificación de excepciones:</span> {_e(fail_fast['justification'])}</p>

<h2>Detalle por dominio</h2>""")
    for d in domains:
        quotes = "".join(f'<div class="quote">«{_e(q)}»</div>' for q in (d.get("evidencia_citada") or [])[:3])
        fix = d.get("medida_correctiva")
        opinion = (f'<p style="font-size:9pt;color:#5B3F8E"><span class="lbl" style="color:#5B3F8E">Opinión de la IA:</span> '
                   f'{_e(d["llm_opinion"]["dictamen"])}; se mantiene el dictamen de las reglas hasta la revisión del auditor.</p>'
                   if d.get("llm_opinion") else "")
        parts.append(f"""<div class="dom"><div class="hd"><b>{_e(SHORT.get(d['domain'], d['domain']))}</b>{_chip(d['dictamen'])}</div>
<div class="norm">{_e('ISO/IEC 27701: ' + ', '.join(d.get('controls', [])))} · {_e('Ley 29733: Art. ' + ', '.join(map(str, d.get('articles', []))))}</div>
{f'<p class="lbl" style="margin-bottom:2px">Evidencia citada</p>{quotes}' if quotes else ''}
<p><span class="lbl">Hallazgo:</span> {_e(d.get('hallazgo'))}</p>
{f'<p><span class="lbl">Medida correctiva:</span> {_e(fix)}</p>' if fix and fix != 'Ninguna.' else ''}
{opinion}
<div class="frags">Fragmentos normativos: {_e(', '.join(d.get('fragments', [])) or '—')}</div></div>""")

    actions = record.get("corrective_actions") or []
    parts.append("<h2>Medidas correctivas priorizadas</h2>")
    parts.append("<ol class='fix'>" + "".join(f"<li>{_e(a)}</li>" for a in actions) + "</ol>" if actions else "<p>Ninguna.</p>")

    # Corta entre frases ("auditor. 1. Deber…"), pero no en abreviaturas como "Art. 14".
    reasons = [r.strip() for r in re.split(r"(?<=[a-záéíóúñ)»]\.)\s+(?=(?:\d\.\s)?[A-ZÁÉÍÓÚÑ¿«])",
                                           record["hitl_trigger"]["reason"]) if r.strip()]
    parts.append(f"""<h2>Revisión humana</h2><div class="review">
<b>Estado:</b> {_e(status)}{' — el informe no se emite hasta que el auditor lo apruebe o rechace.' if pending else ''}
{'<ul>' + ''.join(f'<li>{_e(r)}</li>' for r in reasons) + '</ul>' if record['hitl_trigger']['requires_auditor_signoff'] else ''}</div>
<div class="sign"><div>Auditor líder / DPO</div><div>Fecha y firma</div></div>

<h2>Trazabilidad normativa</h2><table class="trace"><tr><th>Dominio</th><th>Fragmento</th><th>Norma</th><th>Control / artículo</th><th>Texto</th></tr>""")
    for t in record.get("traceability", []):
        ref = t.get("control") or (f"Art. {t['articulo']}" + (f" num. {t['numeral']}" if t.get("numeral") else "") if t.get("articulo") else "—")
        parts.append(f"<tr><td>{_e(SHORT.get(t['domain'], t['domain']))}</td><td>{_e(t['fragment_id'])}</td>"
                     f"<td>{_e(t['norma'])}</td><td>{_e(ref)}</td><td>{_e(t.get('tipo_texto'))}</td></tr>")
    parts.append(f"""</table>
<h2>Evidencia auditada</h2><pre>{_e(record.get('evidence_text', ''))}</pre>
<div class="foot">Generado por {_e(record['agent_id'])} · Supervisor de Consentimientos · Grupo C, Auditoría de Sistemas – UNSA</div>
</body></html>""")
    return "".join(parts)


def find_browser() -> Optional[str]:
    """Edge o Chrome instalados (se usan solo para imprimir el HTML a PDF, sin abrir ventanas)."""
    candidates = [os.environ.get("NAVEGADOR_PDF")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    candidates += [shutil.which(n) for n in ("msedge", "google-chrome", "chrome", "chromium", "chromium-browser")]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def export_pdf(record: Dict[str, Any], path: str | Path, timeout: int = 60) -> Path:
    """Genera el PDF del informe. Lanza RuntimeError si no hay navegador compatible."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("No se encontró Edge ni Chrome para generar el PDF.")
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "informe.html"
        source.write_text(render_html(record), encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={Path(tmp) / 'perfil'}", f"--print-to-pdf={target}", source.as_uri()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("El navegador no pudo generar el PDF.")
    return target
