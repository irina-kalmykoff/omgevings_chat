"""Read a STOP/TPOD regulation into TextComponents, without DSO semantic annotations.

Ported from the team's ``LLM_KG/scripts/clean_text.py``. Only ``Regeling/Tekst.xml``
and ``Regeling/Identificatie.xml`` are read; IMOW files are never opened. Reference
wording is kept, reference target attributes are dropped, and two audits fail the
read rather than silently lose text: every component's visible characters must
survive rendering, and no Al/Term/table cell may sit outside an exported component.

Run as ``python -m omgkg.ingest.dso.stop_tpod --package <dir> --out <file.jsonl>``.
"""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from omgkg.models import Heading, Paragraph, Provenance, TextComponent

Kind = Literal["article", "appendix", "explanatory_note"]

NS = {
    "t": "https://standaarden.overheid.nl/stop/imop/tekst/",
    "d": "https://standaarden.overheid.nl/stop/imop/data/",
}
HIERARCHY = {"Hoofdstuk", "Afdeling", "Paragraaf", "Subparagraaf"}
EXPLANATORY = {"Toelichting", "AlgemeneToelichting", "ArtikelgewijzeToelichting"}
BLOCKS = {
    "Al",
    "Inhoud",
    "Kop",
    "Lijst",
    "Lid",
    "Definitie",
    "Begrippenlijst",
    "Divisietekst",
    "Bijlage",
    "Artikel",
} | EXPLANATORY
MERGED_CELL_ATTRIBUTES = ("namest", "nameend", "morerows")


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _compact(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _field(element: ET.Element, path: str) -> str:
    return _compact(element.findtext(path, default="", namespaces=NS))


def _heading(element: ET.Element) -> str:
    kop = element.find("t:Kop", NS)
    if kop is None:
        return ""
    parts = (_compact("".join(c.itertext())) for c in kop)
    return " ".join(p for p in parts if p)


def render(element: ET.Element, depth: int = 0, notation: bool = True) -> str:
    """Visible text in document order; attributes (including IntRef.ref) are ignored.

    ``notation=False`` is only for the preservation audit: it compares the source
    character stream with the renderer's, without the added layout symbols.
    """
    tag = _local(element)
    if tag == "br":
        return "\n"
    if tag == "table":
        if any(k in e.attrib for e in element.iter() for k in MERGED_CELL_ATTRIBUTES):
            raise ValueError("Merged table cells need explicit layout handling")
        rows = []
        for row in element.findall(".//t:row", NS):
            line_break = " / " if notation else " "
            cells = [
                render(c, depth, notation).strip().replace("\n", line_break)
                for c in row
                if _local(c) == "entry"
            ]
            rows.append((" | " if notation else " ").join(cells))
        return "\n" + "\n".join(rows) + "\n"
    if tag == "Lijst":
        return "\n" + "".join(render(c, depth, notation) for c in element) + "\n"
    if tag == "Li":
        # A nested list goes on a new line, indented under its parent item.
        result = "\n" + "  " * depth + _field(element, "t:LiNummer")
        first = True
        for child in (c for c in element if _local(c) != "LiNummer"):
            if _local(child) == "Lijst":
                result += "\n" + render(child, depth + 1, notation).strip("\n")
            else:
                separator = " " if first else "\n" + "  " * (depth + 1)
                result += separator + render(child, depth + 1, notation).strip()
            first = False
        return result + "\n"
    if tag == "Begrip":
        definition = element.find("t:Definitie", NS)
        text = "" if definition is None else render(definition, depth, notation).strip()
        term = _field(element, "t:Term")
        return "\n" + term + (": " if notation else " ") + text + "\n"

    # Keep inline adjacency: spacing around every element would corrupt numbers,
    # punctuation, units and words with italic fragments.
    result = re.sub(r"\s+", " ", element.text or "")
    for child in element:
        result += render(child, depth, notation)
        result += re.sub(r"\s+", " ", child.tail or "")
    if tag in {"sup", "sub"} and notation:
        result = ("^(" if tag == "sup" else "_(") + result.strip() + ")"
    if tag in BLOCKS:
        result = "\n" + result.strip() + "\n"
    return result


def tidy(text: str) -> str:
    """Strip trailing spaces and collapse blank runs, keeping list indentation."""
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _characters(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _component(
    element: ET.Element,
    kind: Kind,
    context: tuple[Heading, ...],
    document_id: str,
    expression_id: str,
    snapshot_id: str,
) -> TextComponent:
    wid = element.get("wId")
    if not wid:
        raise ValueError(f"Missing wId on {kind}")
    title = _heading(element)
    chunks = [title] if title else []
    paragraphs = []
    for child in element:
        if _local(child) == "Kop":
            continue
        chunk = tidy(render(child))
        if not chunk:
            continue
        start = len("\n\n".join(chunks)) + (2 if chunks else 0)
        chunks.append(chunk)
        if _local(child) == "Lid":
            paragraphs.append(
                Paragraph(
                    w_id=child.get("wId") or "",
                    e_id=child.get("eId"),
                    number=_field(child, "t:LidNummer"),
                    start=start,
                    end=start + len(chunk),
                )
            )
    # Fail rather than silently drop or duplicate visible source text.
    expected = _characters("".join(element.itertext()))
    if expected != _characters(render(element, notation=False)):
        raise ValueError(f"Text preservation audit failed for {wid}")
    path = [h.heading for h in context if h.heading] + ([title] if title else [])
    return TextComponent(
        id=f"{expression_id}#{wid}",
        kind=kind,
        number=_field(element, "t:Kop/t:Nummer"),
        heading=title,
        context=list(context),
        text="\n\n".join(chunks),
        paragraphs=paragraphs,
        provenance=Provenance(
            source_type="legal_text_passage",
            document_id=document_id,
            document_version_id=expression_id,
            text_component_id=wid,
            structural_path=" > ".join(path),
            snapshot_id=snapshot_id,
        ),
    )


def _audit_coverage(root: ET.Element, components: list[TextComponent]) -> None:
    """Every Al, Term and table cell must belong to an exported component."""
    wids = {c.provenance.text_component_id for c in components}
    covered = {id(e) for el in root.iter() if el.get("wId") in wids for e in el.iter()}
    # The regulation's title is metadata, not an omitted legal passage.
    title = root.find("t:RegelingOpschrift", NS)
    covered |= {id(e) for e in title.iter()} if title is not None else set()
    if any(
        _local(e) in {"Al", "Term", "entry"} and id(e) not in covered
        for e in root.iter()
    ):
        raise ValueError("Unexported legal text found outside selected components")


def read_regeling(package: Path, snapshot_id: str) -> list[TextComponent]:
    """Articles in document order, then appendices and explanatory notes."""
    root = ET.parse(package / "Regeling" / "Tekst.xml").getroot()
    identification = ET.parse(package / "Regeling" / "Identificatie.xml").getroot()
    document_id = _field(identification, "d:FRBRWork")
    expression_id = _field(identification, "d:FRBRExpression")
    if not document_id or not expression_id:
        raise ValueError("Document and expression identifiers are required")
    articles: list[TextComponent] = []
    supporting: list[TextComponent] = []

    def make(element: ET.Element, kind: Kind, context: tuple[Heading, ...]) -> None:
        out = articles if kind == "article" else supporting
        out.append(
            _component(element, kind, context, document_id, expression_id, snapshot_id)
        )

    def walk(element: ET.Element, context: tuple[Heading, ...] = ()) -> None:
        tag = _local(element)
        if tag == "Artikel":
            return make(element, "article", context)
        if tag == "Bijlage":
            return make(element, "appendix", context)
        if tag == "Divisietekst" and any(h.kind == "Toelichting" for h in context):
            return make(element, "explanatory_note", context)
        if tag in HIERARCHY | EXPLANATORY:
            context = (*context, Heading(kind=tag, heading=_heading(element)))
        for child in element:
            walk(child, context)

    walk(root)
    components = articles + supporting
    if len({c.id for c in components}) != len(components):
        raise ValueError("Duplicate source component identifiers")
    _audit_coverage(root, components)
    return components


def write_jsonl(components: list[TextComponent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(c.model_dump_json() + "\n" for c in components), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    components = read_regeling(args.package, args.snapshot_id)
    write_jsonl(components, args.out)
    print(f"{len(components)} components, audits passed: {args.out}")


if __name__ == "__main__":
    main()
