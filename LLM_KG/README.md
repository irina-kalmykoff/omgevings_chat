# LLM KG for the Maastricht omgevingsplan

This pipeline reads the same STOP/TPOD delivery package as the hybrid KG.
It exports the cleaned legal text, extracts statements and references with an
LLM, checks their evidence, and resolves references to stable article IDs.

## Layout

| Path | Purpose |
| --- | --- |
| `scripts/clean_text.py` | Exports cleaned articles, supporting text, and source provenance. |
| `scripts/run_extract.py` | Runs extraction, validation, and reference resolution for the selected article. |
| `scripts/extract1.py` | Defines the extraction prompt and requests exact quotes. |
| `scripts/validate1.py` | Checks extraction structure and calculates evidence offsets from source quotes. |
| `scripts/resolve1.py` | Resolves references to articles, numbered paragraphs, and sections. |
| `scripts/verify1.py` | Provides model-based review for a separate verification stage. |
| `tests/` | Regression checks for the text exporter. |
| `data/cleaned/articles.jsonl` | One JSON object per article, in document order. |
| `data/cleaned/articles.txt` | Readable article preview with section context. |
| `data/cleaned/supporting_text.jsonl` | Appendix and explanatory notes. |
| `data/cleaned/manifest.json` | Source and version IDs, hashes, counts, and audit results. |
| `data/extractions/` | One extraction result per article, such as `maastricht-22.36.json`. |
| `data/debug_Log/` | Per-article model-call logs, such as `maastricht-22.36.json.calls.jsonl`. |

## Run the pipeline for one article

1. Run `python3 scripts/clean_text.py` from the `LLM_KG/` folder if you need to
   regenerate the cleaned input. The exporter prints the counts, audit results,
   and output directory.
2. Set `ARTICLE_NUMBER`, `BACKEND`, and `MODEL` at the top of
   `scripts/run_extract.py`. For the OpenAI backend, the run environment needs
   `OPENAI_API_KEY`. In PyCharm, point the run configuration at your local
   `.env` file.
3. Run `scripts/run_extract.py` in PyCharm. The runner validates the model
   response and calculates offsets for exact quotes. For a repeated quote, the
   validator can use the parent statement's span to locate it. Validation
   errors trigger one retry. When only ambiguous references fail, the retry
   sends short candidate passages and asks for a choice for each citation.
   Other validation failures use a full-response retry. If validation still
   fails, the console prints the errors and the prior result is preserved.
4. A successful run resolves references and saves the extraction, validation
   corrections and warnings, and reference resolutions in `data/extractions/`.
   The console prints the status of each citation. Review the descriptions for
   meaning and coverage before using them in the graph.

Each run appends its API attempts to the log in `data/debug_Log/`. Each log
entry records the request, timing, outcome, and raw response when available.

To export from another delivery package or to another folder, run

```sh
python3 scripts/clean_text.py --package /path/to/package --out /path/to/output
```

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
