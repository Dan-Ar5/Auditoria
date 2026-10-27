from __future__ import annotations

import bisect
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import NORMA_ISO, NORMA_LEY, NORMA_REGLAMENTO

MAX_CHARS = 1500       # un artículo/control más largo se subdivide
PARAGRAPH_CHARS = 900  # tamaño objetivo al dividir por párrafos
OVERLAP_CHARS = 150    # ~10-15 % de solapamiento entre párrafos (TIF, 3.4)

RE_ARTICULO = re.compile(r"(?mi)^\s*Art[íi]culo\s+(\d+)\s*[°º]?")
RE_NUMERAL = re.compile(r"(?m)^\s*(\d{1,3}\.\d{1,2}|\d{1,2}[.)])\s+(?=[A-ZÁÉÍÓÚÑ¿])")
RE_CONTROL = re.compile(r"(?m)^\s*([AB]\.\d+\.\d+\.\d+)\b")


def detect_norma(file_name: str) -> str:
    name = file_name.lower()
    if "27701" in name or "iso" in name:
        return NORMA_ISO
    if "016-2024" in name or "reglamento" in name:
        return NORMA_REGLAMENTO
    if "29733" in name or "ley" in name:
        return NORMA_LEY
    return file_name


def _split_paragraphs(text: str) -> List[str]:
    """Divide por párrafos/líneas completas, nunca a mitad de oración, con solapamiento pequeño."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\S)", text) if p.strip()]
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > PARAGRAPH_CHARS:
            chunks.append(current)
            tail = current[-OVERLAP_CHARS:]
            cut = tail.find(". ")
            current = (tail[cut + 2:] if cut != -1 else "") + "\n" + paragraph
        else:
            current = f"{current}\n{paragraph}" if current else paragraph
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _sections(text: str, regex: re.Pattern) -> List[Dict[str, Any]]:
    matches = list(regex.finditer(text))
    sections = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({"key": match.group(1), "start": match.start(), "text": text[match.start():end].strip()})
    return sections


def _split_law_article(article_text: str) -> List[Dict[str, Any]]:
    """Un artículo largo se divide por numeral; cada numeral lleva antepuesta la cabecera del artículo."""
    if len(article_text) <= MAX_CHARS:
        return [{"numeral": None, "text": article_text}]
    header, _, body = article_text.partition("\n")
    numerals = _sections(body, RE_NUMERAL)
    if len(numerals) >= 2:
        intro = body[:numerals[0]["start"]].strip()
        prefix = header.strip() + ("\n" + intro[:400] if intro else "")
        return [{"numeral": n["key"].rstrip(".)"), "text": f"{prefix}\n{n['text']}"} for n in numerals]
    return [{"numeral": None, "text": chunk if i == 0 else f"{header.strip()}\n{chunk}"}
            for i, chunk in enumerate(_split_paragraphs(article_text))]


def fragment_document(file_name: str, pages: List[str]) -> List[Dict[str, Any]]:
    """Chunking estructural: unidad mínima = artículo (ley) o control (ISO), con metadatos trazables."""
    norma = detect_norma(file_name)
    text = ""
    page_starts: List[int] = []
    for page in pages:
        page_starts.append(len(text))
        text += page + "\n"

    def page_of(position: int) -> int:
        return bisect.bisect_right(page_starts, position)

    fragments: List[Dict[str, Any]] = []
    base = {"norma": norma, "origen": file_name, "tipo_texto": "literal", "idioma": "es"}

    if norma == NORMA_ISO:
        base.update({"tipo_de_documento": "estándar internacional", "idioma": "en"})
        controls = _sections(text, RE_CONTROL)
        for section in controls:
            control = section["key"]
            nature = "guia" if control.startswith("B") else "requisito_normativo"
            annex = "Anexo B" if control.startswith("B") else "Anexo A"
            for chunk in _split_paragraphs(section["text"]) if len(section["text"]) > MAX_CHARS else [section["text"]]:
                fragments.append({**base, "control": control, "articulo": None, "numeral": None,
                                  "seccion_jerarquica": f"{annex} > {control}", "naturaleza": nature,
                                  "pagina": page_of(section["start"]), "texto": chunk})
        if controls:
            return fragments
    else:
        base["tipo_de_documento"] = "ley nacional" if norma == NORMA_LEY else "reglamento"
        for section in _sections(text, RE_ARTICULO):
            article = int(section["key"])
            nature = "excepcion" if norma == NORMA_LEY and article == 14 else "requisito_normativo"
            for piece in _split_law_article(section["text"]):
                path = f"{norma} > Artículo {article}" + (f" > numeral {piece['numeral']}" if piece["numeral"] else "")
                fragments.append({**base, "control": None, "articulo": article, "numeral": piece["numeral"],
                                  "seccion_jerarquica": path, "naturaleza": nature,
                                  "pagina": page_of(section["start"]), "texto": piece["text"]})
        if fragments:
            return fragments

    # Sin estructura reconocible (por ejemplo, texto OCR): división por párrafos.
    for chunk in _split_paragraphs(text):
        position = text.find(chunk[:80])
        fragments.append({**base, "control": None, "articulo": None, "numeral": None,
                          "seccion_jerarquica": file_name, "naturaleza": "requisito_normativo",
                          "pagina": page_of(max(position, 0)), "texto": chunk})
    return fragments


def extract_pdf_pages(path: str | Path) -> List[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf es requerido para leer PDF. Instala requirements.txt") from exc
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


class NormativeCorpus:
    """Corpus normativo fragmentado (base JSON + PDF opcionales) con metadatos del TIF."""

    def __init__(self, fragments: Optional[List[Dict[str, Any]]] = None) -> None:
        self.fragments: List[Dict[str, Any]] = []
        self.ingest_report: List[Dict[str, Any]] = []
        for fragment in fragments or []:
            self.add(fragment)

    @classmethod
    def from_file(cls, path: str | Path) -> "NormativeCorpus":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        corpus = cls(data.get("fragments", []))
        corpus.ingest_report.append({"source": Path(path).name, "fragments": len(corpus.fragments), "status": "ok"})
        return corpus

    def add(self, fragment: Dict[str, Any]) -> None:
        fragment = dict(fragment)
        fragment.setdefault("id", f"FR-{len(self.fragments) + 1:04d}")
        fragment.setdefault("tipo_texto", "literal")
        self.fragments.append(fragment)

    def add_pdf_folder(self, folder: str | Path) -> List[Dict[str, Any]]:
        """Agrega los PDF de una carpeta. Omite (y reporta) los escaneados sin texto."""
        report = []
        for pdf in sorted(Path(folder).glob("*.pdf")):
            pages = extract_pdf_pages(pdf)
            chars = sum(len(p.strip()) for p in pages)
            if chars < 20 * max(len(pages), 1):
                report.append({"source": pdf.name, "fragments": 0,
                               "status": f"omitido: sin texto extraíble ({chars} caracteres en {len(pages)} páginas, "
                                         "probablemente escaneado)"})
                continue
            fragments = fragment_document(pdf.name, pages)
            for fragment in fragments:
                self.add(fragment)
            report.append({"source": pdf.name, "fragments": len(fragments), "status": "ok"})
        self.ingest_report.extend(report)
        return report

    def get(self, fragment_id: str) -> Optional[Dict[str, Any]]:
        return next((f for f in self.fragments if f["id"] == fragment_id), None)

    def filter(self, **criteria: Any) -> List[Dict[str, Any]]:
        return [f for f in self.fragments if matches(f, criteria)]

    def __len__(self) -> int:
        return len(self.fragments)


def matches(fragment: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    """Filtro de metadatos: cada criterio acepta un valor o una lista de valores admitidos."""
    for key, expected in criteria.items():
        if expected is None:
            continue
        allowed: Iterable[Any] = expected if isinstance(expected, (list, tuple, set)) else [expected]
        if fragment.get(key) not in allowed:
            return False
    return True
