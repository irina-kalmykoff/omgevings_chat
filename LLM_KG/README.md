# LLM KG — legal text preparation for the knowledge graph

The text preparation stage of the independent LLM knowledge graph pipeline for
the Maastricht omgevingsplan. It reads the same STOP/TPOD delivery package as the
hybrid KG, and exports the cleaned legal text for LLM extraction
## Layout

```
LLM_KG/
  scripts/          Python: legal text exporter
  tests/            regression checks for the exporter
  data/cleaned/     generated article text, supporting text and export manifest
```

To run the exporter:
   ```
   python3 scripts/clean_text.py
   ```

   On success it prints the article and supporting-text counts, confirms that
   the text preservation and coverage audits passed, and shows the output folder.
   Re-running replaces the generated files. The original source files are kept
   unchanged.


To use another delivery package or output folder:

```
python3 scripts/clean_text.py --package /path/to/package --out /path/to/output
```

Generated data is ignored by Git and can be recreated with the command above.

## Files

| File | What it is |
| --- | --- |
| `scripts/clean_text.py` | reads the STOP legal text and document identifiers, exports cleaned text and provenance, and checks preservation and coverage |
| `tests/test_clean_text.py` | regression checks for the text exporter |
| `data/cleaned/articles.jsonl` | one JSON object per article, in document order |
| `data/cleaned/articles.txt` | readable article preview, including section context |
| `data/cleaned/supporting_text.jsonl` | appendix and explanatory notes, identified separately from articles |
| `data/cleaned/manifest.json` | source/version IDs, input and exporter hashes, counts, input boundary and audit results |

## What cleaning keeps

The exporter keeps the legal wording, article headings and numbers, paragraph
numbers, nested lists, tables and visible references such as “Artikel 22.26”.
Section headings remain as context because later articles may inherit their scope.
Reserved articles remain numbered records without invented body text.

XML syntax, attributes and bold/italic formatting are removed. Internal reference
target attributes are left out so the LLM can extract relationships from the
wording. Structural IDs and document/version identity remain in provenance
metadata. The exporter does not read `OW-bestanden`, existing graph relationships
or model-generated labels.

Line breaks preserve paragraphs and list nesting. Tables use one row per line,
with ` | ` between cells and ` / ` for line breaks inside a cell. Superscripts
and subscripts use `^(value)` and `_(value)` so units and formulae remain readable.
Cleaning does not translate, summarise, correct or truncate the legal wording.

## Use the text for extraction

Each article has `id`, `kind`, `number`, `heading`, `context`, `text` and
`provenance`. Pass `text` and, where needed, the structural `context` to the model.
The heading is already included in `text`; avoid adding it twice.

Keep `id` and `provenance` in the application to attach predictions to their
source. `provenance.paragraphs` contains paragraph IDs and Python string offsets
`[start:end]` into `text`. These refer to the cleaned text, not XML bytes; each
paragraph occurs once in its article.

## Verification

`tests/test_clean_text.py` checks that the exporter preserves the source text
and produces consistent output. Run it directly from this `LLM_KG/` folder:

```
python3 tests/test_clean_text.py -v
```

The tests check:

- visible references stay in the text while internal target attributes are removed;
- nested lists, indentation, superscripts, table line breaks and empty cells are
  preserved, and merged table cells are rejected;
- the current source produces 308 articles, 473 article paragraphs, one appendix
  and 309 explanatory notes, with distinct record IDs;
- letters and digits match the source in order, without loss or duplication;
- paragraph offsets point to the correct text within each article;
- the exporter reads only `Tekst.xml` and `Identificatie.xml`, leaves semantic
  annotation fields out of article output, and produces identical files on repeat runs.

The tests use the committed source package and write export files to a temporary
folder that is removed afterwards. They need no extra packages, Neo4j or API key.
A successful run ends with `Ran 8 tests` and `OK`.

To discover and run all `test*.py` files in `tests/` (currently the same eight
checks), use:

```
python3 -m unittest discover -s tests -v
```

The export fails if visible source characters are lost or duplicated (ignoring
whitespace and added layout notation), source IDs repeat, or a legal text block
is left uncovered. Articles and supporting text together cover the source
content; the regulation title remains document metadata.
