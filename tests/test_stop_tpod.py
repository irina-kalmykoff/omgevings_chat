"""STOP/TPOD reading: legal wording, source isolation, lid offsets and audits."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from omgkg.ingest.dso.stop_tpod import NS, read_regeling, render, tidy, write_jsonl
from omgkg.models import TextComponent

SNAPSHOT = (
    Path(__file__).parents[1] / "source_data/Maastricht-DSO-production-2026-10-02"
)
IDENTIFICATIE = f"""<d:ExpressionIdentificatie xmlns:d="{NS["d"]}">
<d:FRBRWork>/akn/nl/act/gm9999/2026/test</d:FRBRWork>
<d:FRBRExpression>/akn/nl/act/gm9999/2026/test/nld@1</d:FRBRExpression>
</d:ExpressionIdentificatie>"""
ARTICLE = """<t:Artikel wId="art_1"><t:Kop><t:Nummer>1.1</t:Nummer><t:Opschrift>Dakkapel
</t:Opschrift></t:Kop>
<t:Lid wId="art_1__para_1" eId="para_1"><t:LidNummer>1</t:LidNummer>
<t:Al>Een dakkapel is <t:IntRef ref="X">vergunningvrij</t:IntRef>.</t:Al></t:Lid>
<t:Lid wId="art_1__para_2" eId="para_2"><t:LidNummer>2</t:LidNummer>
<t:Al>Niet hoger dan 1,75 m.</t:Al></t:Lid></t:Artikel>"""
TOELICHTING = """<t:Toelichting><t:Kop><t:Opschrift>Toelichting</t:Opschrift></t:Kop>
<t:Divisietekst wId="div_1"><t:Inhoud><t:Al>Waarom dit zo is.</t:Al></t:Inhoud>
</t:Divisietekst></t:Toelichting>"""


def xml(body: str) -> ET.Element:
    return ET.fromstring(f'<t:Inhoud xmlns:t="{NS["t"]}">{body}</t:Inhoud>')


def package(tmp_path: Path, body: str) -> Path:
    regeling = tmp_path / "Regeling"
    regeling.mkdir()
    (regeling / "Identificatie.xml").write_text(IDENTIFICATIE, encoding="utf-8")
    tekst = f'<t:RegelingCompact xmlns:t="{NS["t"]}">{body}</t:RegelingCompact>'
    (regeling / "Tekst.xml").write_text(tekst, encoding="utf-8")
    return tmp_path


def test_reference_attributes_dropped_but_wording_kept() -> None:
    result = tidy(
        render(
            xml(
                '<t:Al>Zie <t:IntRef ref="SECRET_TARGET">Artikel 22.26</t:IntRef>, '
                "niet <t:i>alle</t:i> gevallen.</t:Al>"
            )
        )
    )
    assert result == "Zie Artikel 22.26, niet alle gevallen."


def test_nested_list_keeps_conditions_and_indentation() -> None:
    result = tidy(
        render(
            xml(
                "<t:Al>Dit geldt als:</t:Al><t:Lijst><t:Li><t:LiNummer>a.</t:LiNummer>"
                "<t:Al>voldaan wordt aan:</t:Al><t:Lijst><t:Li><t:LiNummer>1."
                "</t:LiNummer><t:Al>niet hoger dan 5 m;</t:Al></t:Li><t:Li>"
                "<t:LiNummer>2.</t:LiNummer><t:Al>niet groter dan 70 m<t:sup>2</t:sup>."
                "</t:Al></t:Li></t:Lijst></t:Li><t:Li><t:LiNummer>b.</t:LiNummer>"
                "<t:Al>een andere optie.</t:Al></t:Li></t:Lijst>"
            )
        )
    )
    assert "a. voldaan wordt aan:" in result
    assert "\n  1. niet hoger dan 5 m;" in result
    assert "\n  2. niet groter dan 70 m^(2)." in result
    assert "\nb. een andere optie." in result
    assert result.count("niet hoger") == 1


def test_table_cells_line_breaks_and_empty_cells() -> None:
    result = tidy(
        render(
            xml(
                "<t:table><t:tgroup><t:tbody><t:row>"
                "<t:entry><t:Al>Stof<t:br/>groep A</t:Al></t:entry>"
                "<t:entry/><t:entry><t:Al>50 kg</t:Al></t:entry>"
                "</t:row></t:tbody></t:tgroup></t:table>"
            )
        )
    )
    assert result == "Stof / groep A |  | 50 kg"


def test_merged_table_cells_are_rejected() -> None:
    with pytest.raises(ValueError, match="Merged table"):
        render(
            xml('<t:table><t:row><t:entry morerows="1">x</t:entry></t:row></t:table>')
        )


def test_fixture_package_reads_articles_then_notes_with_provenance(
    tmp_path: Path,
) -> None:
    hoofdstuk = (
        "<t:Lichaam><t:Hoofdstuk><t:Kop><t:Label>Hoofdstuk</t:Label><t:Nummer>1"
        f"</t:Nummer></t:Kop>{ARTICLE}</t:Hoofdstuk></t:Lichaam>"
    )
    article, note = read_regeling(
        package(tmp_path, hoofdstuk + TOELICHTING), snapshot_id="test-snapshot"
    )

    assert (article.kind, note.kind) == ("article", "explanatory_note")
    assert article.id == "/akn/nl/act/gm9999/2026/test/nld@1#art_1"
    # The lid number stays on its own line, as in the real snapshot.
    lid_texts = ["1\nEen dakkapel is vergunningvrij.", "2\nNiet hoger dan 1,75 m."]
    assert article.text == "\n\n".join(["1.1 Dakkapel", *lid_texts])
    assert [article.text[p.start : p.end] for p in article.paragraphs] == lid_texts
    assert [p.w_id for p in article.paragraphs] == ["art_1__para_1", "art_1__para_2"]
    assert article.provenance.text_component_id == "art_1"
    assert article.provenance.structural_path == "Hoofdstuk 1 > 1.1 Dakkapel"
    assert article.provenance.snapshot_id == "test-snapshot"
    assert note.text == "Waarom dit zo is."


def test_output_is_deterministic(tmp_path: Path) -> None:
    pkg = package(tmp_path, f"<t:Lichaam>{ARTICLE}</t:Lichaam>")
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(read_regeling(pkg, "s"), first)
    write_jsonl(read_regeling(pkg, "s"), second)
    assert first.read_bytes() == second.read_bytes()
    line = first.read_text(encoding="utf-8").splitlines()[0]
    assert TextComponent.model_validate_json(line).provenance.document_id


def test_legal_text_outside_any_component_fails_the_read(tmp_path: Path) -> None:
    body = f"<t:Lichaam><t:Al>Verdwaalde regel.</t:Al>{ARTICLE}</t:Lichaam>"
    with pytest.raises(ValueError, match="Unexported legal text"):
        read_regeling(package(tmp_path, body), "s")


def test_maastricht_snapshot_reads_completely() -> None:
    components = read_regeling(SNAPSHOT, "maastricht-dso-2026-10-02")
    articles = [c for c in components if c.kind == "article"]
    assert len(articles) == 308
    assert sum(len(a.paragraphs) for a in articles) == 473
    assert sum(c.kind == "appendix" for c in components) == 1
    assert sum(c.kind == "explanatory_note" for c in components) == 309
    assert len({c.id for c in components}) == 618
