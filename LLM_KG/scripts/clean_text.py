"""Export legal text and structural provenance without DSO semantic annotations.

Uses only the Python standard library. Does not read IMOW files or Neo4j.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = ROOT / "source_data/Maastricht-DSO-production-2026-10-02"
NS = {"t": "https://standaarden.overheid.nl/stop/imop/tekst/",
      "d": "https://standaarden.overheid.nl/stop/imop/data/"}
HIERARCHY = {"Hoofdstuk", "Afdeling", "Paragraaf", "Subparagraaf"}
BLOCKS = {"Al", "Inhoud", "Kop", "Lijst", "Lid", "Definitie",
          "Begrippenlijst", "Divisietekst", "AlgemeneToelichting",
          "ArtikelgewijzeToelichting", "Toelichting", "Bijlage", "Artikel"}


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def compact(value):
    return re.sub(r"\s+", " ", value or "").strip()


def field(element, path):
    return compact(element.findtext(path, default="", namespaces=NS))


def heading(element):
    kop = element.find("t:Kop", NS)
    if kop is None:
        return ""
    return " ".join(compact("".join(c.itertext())) for c in kop
                    if compact("".join(c.itertext())))


def render(element, depth=0, notation=True):
    """Keep visible text in order; attributes (including IntRef.ref) are ignored.

    notation=False is used only for the loss/duplication audit, comparing the
    source character stream with the renderer without added layout symbols.
    """
    tag = local(element)
    if tag == "br":
        return "\n"
    if tag == "table":
        if any(any(key in e.attrib for key in ("namest", "nameend", "morerows"))
               for e in element.iter()):
            raise ValueError("Merged table cells need explicit layout handling")
        rows = []
        for row in element.findall(".//t:row", NS):
            cells = [render(c, depth, notation).strip().replace("\n", " / " if notation else " ")
                     for c in row if local(c) == "entry"]
            rows.append(" | ".join(cells) if notation else " ".join(cells))
        return "\n" + "\n".join(rows) + "\n"
    if tag == "Lijst":
        return "\n" + "".join(render(c, depth, notation) for c in element) + "\n"
    if tag == "Li":
        label = field(element, "t:LiNummer")
        # Keep a nested list on a new line, indented under its parent item.
        first = True
        result = "\n" + "  " * depth + label
        for child in (c for c in element if local(c) != "LiNummer"):
            if local(child) == "Lijst":
                result += "\n" + render(child, depth + 1, notation).strip("\n")
            else:
                result += (" " if first else "\n" + "  " * (depth + 1)) + render(child, depth + 1, notation).strip()
            first = False
        return result + "\n"
    if tag == "Begrip":
        term = field(element, "t:Term")
        definition = element.find("t:Definitie", NS)
        text = render(definition, depth, notation).strip() if definition is not None else ""
        return "\n" + term + (": " if notation else " ") + text + "\n"

    # Preserve inline adjacency: adding spaces around every XML element can
    # corrupt numbers, punctuation, units and words with italic fragments.
    result = re.sub(r"\s+", " ", element.text or "")
    for child in element:
        result += render(child, depth, notation)
        result += re.sub(r"\s+", " ", child.tail or "")
    if tag in {"sup", "sub"} and notation:
        result = ("^(" if tag == "sup" else "_(") + result.strip() + ")"
    if tag in BLOCKS:
        result = "\n" + result.strip() + "\n"
    return result


def tidy(text):
    lines = [line.rstrip() for line in text.splitlines()]
    # Retain intentional list indentation, but remove indentation-only lines.
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def source(element):
    return {"wId": element.get("wId"), "eId": element.get("eId")}


def characters(value):
    return re.sub(r"\s+", "", value)


def make_record(element, kind, context, document_id, expression_id):
    wid = element.get("wId")
    if not wid:
        raise ValueError(f"Missing wId on {kind}")
    title = heading(element)
    chunks = [title] if title else []
    paragraphs = []
    for child in element:
        if local(child) == "Kop":
            continue
        chunk = tidy(render(child))
        if not chunk:
            continue
        start = len("\n\n".join(chunks)) + (2 if chunks else 0)
        chunks.append(chunk)
        if local(child) == "Lid":
            paragraphs.append({**source(child), "number": field(child, "t:LidNummer"),
                               "start": start, "end": start + len(chunk)})
    text = "\n\n".join(chunks)
    # Fail rather than silently drop or duplicate any visible source text.
    expected = characters("".join(element.itertext()))
    rendered = characters(render(element, notation=False))
    if expected != rendered:
        raise ValueError(f"Text preservation audit failed for {wid}")
    return {"id": expression_id + "#" + wid, "kind": kind,
            "number": field(element, "t:Kop/t:Nummer"), "heading": title,
            "context": list(context), "text": text,
            "provenance": {"document_id": document_id, "expression_id": expression_id,
                           "source_file": "Regeling/Tekst.xml", **source(element),
                           "paragraphs": paragraphs}}


def collect(package):
    text_path = package / "Regeling/Tekst.xml"
    root = ET.parse(text_path).getroot()
    identification = ET.parse(package / "Regeling/Identificatie.xml").getroot()
    document_id = field(identification, "d:FRBRWork")
    expression_id = field(identification, "d:FRBRExpression")
    if not document_id or not expression_id:
        raise ValueError("Document and expression identifiers are required")
    articles, supporting = [], []

    def walk(element, context=()):
        tag = local(element)
        if tag == "Artikel":
            articles.append(make_record(element, "article", context, document_id, expression_id))
            return
        if tag == "Bijlage":
            supporting.append(make_record(element, "appendix", context, document_id, expression_id))
            return
        if tag == "Divisietekst" and any(x["kind"] == "Toelichting" for x in context):
            supporting.append(make_record(element, "explanatory_note", context, document_id, expression_id))
            return
        if tag in HIERARCHY | {"Toelichting", "AlgemeneToelichting", "ArtikelgewijzeToelichting"}:
            context = (*context, {"kind": tag, "heading": heading(element)})
        for child in element:
            walk(child, context)

    walk(root)
    records = articles + supporting
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate source component identifiers")
    # A complete partition of legal/explanatory content: no omitted Al or table
    # cells hidden in a source section that the walker does not recognise.
    covered = set()
    record_wids = {r["provenance"]["wId"] for r in records}
    for element in root.iter():
        if element.get("wId") in record_wids:
            covered.update(id(e) for e in element.iter())
    uncovered = [e for e in root.iter() if local(e) in {"Al", "Term", "entry"}
                 and id(e) not in covered]
    # The regulation's title is metadata, not an omitted legal passage.
    title_node = root.find("t:RegelingOpschrift", NS)
    title_ids = {id(e) for e in title_node.iter()} if title_node is not None else set()
    if any(id(e) not in title_ids for e in uncovered):
        raise ValueError("Unexported legal text found outside selected components")
    return articles, supporting


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")


def export(package, output):
    articles, supporting = collect(package)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "articles.jsonl", articles)
    write_jsonl(output / "supporting_text.jsonl", supporting)
    preview = []
    for record in articles:
        preview.append("\n".join(c["heading"] for c in record["context"] if c["heading"])
                       + "\n\n" + record["text"])
    (output / "articles.txt").write_text(("\n\n" + "=" * 72 + "\n\n").join(preview)
                                         + "\n", encoding="utf-8")
    inputs = [package / "Regeling/Tekst.xml", package / "Regeling/Identificatie.xml"]
    manifest = {"format_version": 1,
                "document_title": compact("".join(ET.parse(inputs[0]).getroot().find("t:RegelingOpschrift", NS).itertext())),
                "document_id": articles[0]["provenance"]["document_id"],
                "expression_id": articles[0]["provenance"]["expression_id"],
                "inputs_sha256": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in inputs},
                "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "counts": {"articles": len(articles),
                           "paragraphs": sum(len(r["provenance"]["paragraphs"]) for r in articles),
                           "appendices": sum(r["kind"] == "appendix" for r in supporting),
                           "explanatory_notes": sum(r["kind"] == "explanatory_note" for r in supporting),
                           "article_text_characters": sum(len(r["text"]) for r in articles)},
                "audit": {"visible_text_preserved": True, "all_content_covered": True},
                "model_input_fields": ["number", "heading", "context", "text"],
                "notes": ["No IMOW annotations, graph edges or model labels are read.",
                          "Reference wording is retained; reference target attributes are excluded.",
                          "Supporting text is separate; explanatory notes are not operative rules.",
                          "sup/sub are rendered as ^(value)/_(value); table cells use | separators."]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--out", type=Path, default=ROOT / "LLM_KG/data/cleaned")
    args = parser.parse_args()
    manifest = export(args.package.resolve(), args.out.resolve())
    print(json.dumps(manifest["counts"], indent=2))
    print(f"Text preservation and coverage audits passed. Output: {args.out.resolve()}")


if __name__ == "__main__":
    main()
