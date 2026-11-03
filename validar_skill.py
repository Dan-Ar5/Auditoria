"""Demostración reproducible del segundo entregable, sin decisiones humanas simuladas."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agente import (OllamaReasoner, build_agent, build_evidence_matrix, export_csv,
                    export_json, export_markdown, export_xlsx)

BASE = Path(__file__).resolve().parent
CASES = {
    'caso_conforme.txt': ('CONFORME', 'EMITIDO'),
    'caso_tiendaandina.txt': ('NO_CONFORME', 'PENDIENTE_REVISION_AUDITOR'),
    'caso_banco.txt': ('NO_CONFORME', 'PENDIENTE_REVISION_AUDITOR'),
    'caso_insuficiente.txt': ('NO_CONFORME', 'PENDIENTE_REVISION_AUDITOR'),
    'caso_inyeccion.txt': ('NO_CONFORME', 'PENDIENTE_REVISION_AUDITOR'),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', type=Path, help='carpeta nueva para los resultados')
    args = parser.parse_args()
    output = args.salida or BASE / 'out' / ('validacion_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    if output.exists() and any(output.iterdir()):
        parser.error('La carpeta de salida debe estar vacía; se conservan las ejecuciones anteriores.')
    output.mkdir(parents=True, exist_ok=True)
    agent, _ = build_agent(mode='local', out_dir=output, include_pdfs=False, reasoner=OllamaReasoner(enabled=False))
    records = []
    checks = []
    for name, expected in CASES.items():
        evidence = (BASE / 'evidencias' / name).read_text(encoding='utf-8')
        record = agent.audit_evidence(evidence, name)
        records.append(record)
        export_markdown(record, output / f'informe_{Path(name).stem}.md')
        actual = (record['overall_status'], record['review_status'])
        checks.append({'case': name, 'expected': list(expected), 'actual': list(actual), 'passed': actual == expected})
        print(f'{name}: {actual[0]} / {actual[1]}')
    export_json(records, output / 'informes.json')
    export_csv(records, output / 'informes.csv')
    try:
        export_xlsx(records, output / 'informes.xlsx')
        excel = 'generado'
    except RuntimeError as exc:
        excel = str(exc)
    export_json(build_evidence_matrix(records, agent.mcp.call_log, agent.hitl_queue.decisions), output / 'matriz_evidencias.json')
    if agent.hitl_queue.decisions:
        raise RuntimeError('Esta validación no debe aprobar o rechazar tickets.')
    result = {'mode': 'local', 'ollama_enabled': False, 'corpus_fragments': len(agent.mcp.corpus),
              'checks': checks, 'passed': all(c['passed'] for c in checks),
              'pending_reviews': len(agent.hitl_queue.list_pending()), 'human_decisions': 0, 'excel': excel,
              'scope': 'Casos ficticios; verificación funcional de criterios parciales, no certificación legal.'}
    (output / 'validacion.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Resultados: {output.resolve()}')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
