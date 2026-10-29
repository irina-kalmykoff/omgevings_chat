"""Regression checks for legal wording, source isolation and evidence offsets."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/clean_text.py"
SPEC = importlib.util.spec_from_file_location("clean_text", SCRIPT)
clean = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clean)


def xml(body):
    return ET.fromstring(f'<t:Inhoud xmlns:t="{clean.NS["t"]}">{body}</t:Inhoud>')


class RenderingTests(unittest.TestCase):
    def test_reference_attributes_removed_but_visible_wording_kept(self):
        result = clean.tidy(clean.render(xml(
            '<t:Al>Zie <t:IntRef ref="SECRET_TARGET">Artikel 22.26</t:IntRef>, '
            'niet <t:i>alle</t:i> gevallen.</t:Al>')))
        self.assertEqual(result, "Zie Artikel 22.26, niet alle gevallen.")

    def test_nested_list_condition_and_indentation_preserved(self):
        result = clean.tidy(clean.render(xml(
            '<t:Al>Dit geldt als:</t:Al><t:Lijst><t:Li><t:LiNummer>a.</t:LiNummer>'
            '<t:Al>voldaan wordt aan:</t:Al><t:Lijst><t:Li><t:LiNummer>1.</t:LiNummer>'
            '<t:Al>niet hoger dan 5 m;</t:Al></t:Li><t:Li><t:LiNummer>2.</t:LiNummer>'
            '<t:Al>niet groter dan 70 m<t:sup>2</t:sup>.</t:Al></t:Li></t:Lijst>'
            '</t:Li><t:Li><t:LiNummer>b.</t:LiNummer><t:Al>een andere optie.</t:Al>'
            '</t:Li></t:Lijst>')))
        self.assertIn("a. voldaan wordt aan:", result)
        self.assertIn("\n  1. niet hoger dan 5 m;", result)
        self.assertIn("\n  2. niet groter dan 70 m^(2).", result)
        self.assertIn("\nb. een andere optie.", result)
        self.assertEqual(result.count("niet hoger"), 1)

    def test_table_cells_line_breaks_and_empty_cells(self):
        result = clean.tidy(clean.render(xml(
            '<t:table><t:tgroup><t:tbody><t:row>'
            '<t:entry><t:Al>Stof<t:br/>groep A</t:Al></t:entry>'
            '<t:entry/><t:entry><t:Al>50 kg</t:Al></t:entry>'
            '</t:row></t:tbody></t:tgroup></t:table>')))
        self.assertEqual(result, "Stof / groep A |  | 50 kg")

    def test_merged_table_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Merged table"):
            clean.render(xml('<t:table><t:tgroup><t:tbody><t:row>'
                             '<t:entry morerows="1">x</t:entry>'
                             '</t:row></t:tbody></t:tgroup></t:table>'))


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.articles, cls.supporting = clean.collect(clean.DEFAULT_PACKAGE)
        cls.root = ET.parse(clean.DEFAULT_PACKAGE / "Regeling/Tekst.xml").getroot()
        cls.by_wid = {e.get("wId"): e for e in cls.root.iter() if e.get("wId")}

    def test_expected_components_and_distinct_source_ids(self):
        self.assertEqual(len(self.articles), 308)
        self.assertEqual(sum(len(r["provenance"]["paragraphs"]) for r in self.articles), 473)
        self.assertEqual(sum(r["kind"] == "appendix" for r in self.supporting), 1)
        self.assertEqual(sum(r["kind"] == "explanatory_note" for r in self.supporting), 309)
        self.assertEqual(len({r["id"] for r in self.articles + self.supporting}), 618)

    def test_exported_content_matches_source_without_loss_or_duplication(self):
        # Independent of render's audit: every source letter/digit must occur
        # exactly once and in order, in the actual saved-record text.
        def letters(value):
            return "".join(c for c in value if c.isalnum())
        for record in self.articles + self.supporting:
            original = self.by_wid[record["provenance"]["wId"]]
            self.assertEqual(letters(record["text"]), letters("".join(original.itertext())),
                             record["id"])

    def test_every_paragraph_offset_resolves_to_its_own_text(self):
        for article in self.articles:
            previous_end = 0
            for paragraph in article["provenance"]["paragraphs"]:
                self.assertGreaterEqual(paragraph["start"], previous_end)
                expected = clean.tidy(clean.render(self.by_wid[paragraph["wId"]]))
                self.assertEqual(article["text"][paragraph["start"]:paragraph["end"]], expected)
                previous_end = paragraph["end"]

    def test_export_uses_only_text_and_identification_and_is_repeatable(self):
        original_parse = clean.ET.parse
        reads = []
        def record_parse(path, *args, **kwargs):
            reads.append(Path(path).name)
            return original_parse(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(clean.ET, "parse", side_effect=record_parse):
                clean.export(clean.DEFAULT_PACKAGE, output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            clean.export(clean.DEFAULT_PACKAGE, output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            records = [json.loads(line) for line in (output / "articles.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 308)
            self.assertNotRegex((output / "articles.jsonl").read_text(),
                                r'"(?:deontic|overrides|ref|refereert_naar|GELDT_VOOR|OP_LOCATIE)"')
        self.assertEqual(set(reads), {"Tekst.xml", "Identificatie.xml"})


if __name__ == "__main__":
    unittest.main()
