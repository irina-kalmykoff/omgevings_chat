# Deontic extraction — findings log

A running log of results and decisions from building the LLM deontic extractor
and the knowledge-graph layer for the omgevingsplan. Newest entry first.

---

## 2026-10-21 — Step 3 validation (building, monument, afwijken, discharge), and write hygiene

Ran the activity-anchored validation on `Bouwactiviteit`, the monument activity,
the afwijken activity, and the household-wastewater-discharge activity: list the
governing articles with their written force and overrides, and check each against
the article text.

Method correction, up front: a first pass judged the tags from article titles and
flagged several as wrong. Reading the actual text reversed almost all of them —
the titles mislead, and the LLM tags were mostly right. That is the main lesson
of this step: tag validation has to read the rule text, not the opschrift.

Coverage: the governing-article path first under-counted because it only reached
articles whose own text governs the activity; climbing from each rule's text up
to its containing Artikel (`BEVAT*0..3`) gave the full set.

What the text showed (correcting the first-pass calls):

- Monument (22.287–22.295) are indieningsvereisten — "bij de aanvraag worden de
  volgende gegevens en bescheiden verstrekt". Genuine obligations; the uniform
  `obligation` tagging is correct. 22.295 (overeenkomstige toepassing) is a
  modification/applicability clause (null). The permit prohibition for monument
  work lives elsewhere, not in these articles.
- 22.23 Algemene afbakeningseisen: the text is "Artikel 22.27 en Artikel 22.36
  zijn niet van toepassing op een activiteit ... [op een illegaal bouwwerk]". It
  genuinely disapplies 22.27 and 22.36, so the model's overrides to them are
  correct, and `prohibition` (a restriction on a permission) is defensible. This
  also corroborates the derived-override logic.
- 22.25 Mantelzorg: a deeming clause ("mantelzorg wordt aangemerkt als
  functioneel verbonden met het hoofdgebouw") — constitutive, so `null` is right.
- 22.34: "kunnen aan een omgevingsvergunning ... voorschriften worden verbonden"
  — the authority may attach conditions; permission/empowerment, so the
  `permission` tag is defensible (and points at the empowerment class).
- 22.40 Overgangsrecht: a transitional provision; `permission` is a rough fit —
  the real gap is a temporal / overgangsrecht category.
- Discharge (22.145–22.150), a clean fourth case: scope (22.145) and measurement
  (22.150) are `null`, submission/treatment requirements are obligations (22.146,
  22.148, 22.149), and 22.147 is a genuine prohibition (a grinder-waste ban). All
  correct on the text. 22.146 and 22.149 also carry exemption sub-lids ("het
  eerste en tweede lid gelden niet voor ...") inside an obligation article — the
  model tagged by the primary norm (the lid-granularity point again).

Net: across four activities, none of the tags flagged on first read survive as
clear errors once the text is read. The LLM tagging holds up better than a
title-based review suggested.

Genuine output of the validation — modelling gaps, not tag errors:

- Assessment / decision rules (beoordelingsregels: 22.29–22.33, 22.281–22.282)
  and measurement conventions (22.24, 22.150) are addressed to the deciding
  authority or are conventions, not citizen conduct; the four citizen-facing tags
  fit them awkwardly. v1 category.
- Modification / overeenkomstige toepassing (22.37, 22.295). v1.
- Temporal / overgangsrecht (22.40). v1.

Write hygiene (independent of adjudication): articles carried OVERRIDES from more
than one tagging pass because `--write` used MERGE and never removed old edges.
Fixed: `write_back` now clears an article's outgoing OVERRIDES before writing the
new ones, so a re-tag replaces rather than accumulates.

Derived-override pass (`prototype/derive_overrides.cypher`): a graph step that
composes each OVERRIDES edge's net effect from its type and the target's deontic
(exception -> exemption; restriction on permission/exemption -> prohibition;
restriction on obligation -> obligation), writes it onto the edge
(`derived_effect`), and reports where the overriding article's own LLM tag
disagrees. Running it corroborated the entire restriction class (22.23, 22.28,
22.38, 22.39, 22.61a all agree — the 22.38 win, confirmed). A first composition
used `exception -> permission`, which falsely flagged the canonical exemption
22.27; corrected to `exception -> exemption`, aligning with v0 (the graph
composition and the LLM tags cross-check each other). The remaining exception
disagreements are not tag errors but v1 categories resurfacing in the override
layer: "in afwijking van Artikel X" articles (22.64, 22.103) are modifications /
derogations mislabelled as `exception` — the LLM's obligation tag is right, and
the override-type vocabulary needs a `modification` type (cue "in afwijking
van"); and eerbiedigende-werking grandfather clauses (22.99, 22.102) are the
temporal class, with genuinely mixed force.

Guard verdict: the guards did their narrow job (no invalid deontic values, no
fake-number targets). The validation turned up no schema violations in the
written output; the open questions are modelling categories, not guard failures.

---

## 2026-10-20 — gpt-4o vs local baseline, adjudication, prompt sharpening, a derived-override design, and the graph-grounded use case

### Setup

The extractor (`prototype/scripts/deontic_extract.py`) runs one code path that switches
between a local model (qwen2.5 via Ollama) and the OpenAI API. For each article
it assigns `statement_type` (prescriptive / constitutive), a `deontic` tag
(obligation / prohibition / permission / exemption) and `OVERRIDES` edges, under
ontology v0. We compared qwen2.5:7b (local) against gpt-4o (hosted), temperature
0, identical prompt and few-shot, scored against `prototype/gold_deontic.csv` —
38 articles hand-labelled by us against the v0 definitions.

### Two methodology issues found this session (read these first)

1. The first runs used the original prompt, not the sharpened one. A sharpened
   prompt had been committed earlier but was overwritten on disk before those
   runs, so the headline numbers and the six-case adjudication below reflect the
   original instruction. The sharpened prompt has since been re-applied and
   re-run (see "Re-run with the sharpened prompt").

2. The few-shot examples leak into the gold set. All four worked examples in the
   prompt (22.26, 22.27, 22.28, 1.1) are themselves gold articles. The model is
   shown the answers to 4 of the 38 it is then scored on, so those four are
   guaranteed-correct and the agreement is inflated by up to 4. The honest figure
   is agreement on the articles the model was not shown.

### Headline results (original prompt)

gpt-4o lands at 31–32 / 38, the same as the 7b baseline. Per-tag (one gpt-4o
run): constitutive 9/10, exemption 2/2, obligation 11/12, permission 2/4,
prohibition 7/10. Model size is not the bottleneck here — the errors sit in
ambiguous and structural cases, not in model capacity. (Both figures still carry
the 4-article leakage above.)

Temperature 0 is not deterministic. Across two gpt-4o runs on the same 38
articles, three of them (22.11, 22.12, 22.23) changed their label between runs.
Any single accuracy number therefore carries run-to-run noise.

### How the prompt was changed (original -> sharpened)

The original `SYSTEM_PROMPT` gave statement_type as a one-line definition, a
single "deontic cues" paragraph, and one note that re-imposing a base rule is
tagged "prohibition with OVERRIDES(restriction)". The sharpened version:

- decides statement_type first, with an explicit prescriptive-vs-constitutive
  rule: Dutch drafting states obligations as present-tense facts ("is aangesloten
  op", "voldoet aan", "is zodanig dat", "ligt haaks", "bedraagt ten minste"), and
  a declarative phrasing does not make an article constitutive;
- states that a performance/presence requirement written as a plain fact is an
  obligation, and that "is geen ... aanwezig" / "wordt niet ... toegepast" is a
  prohibition;
- says a measurement/counting convention is constitutive only when it stands
  alone; beside a behavioural norm, tag the article by the norm;
- requires `deontic` to be exactly one of the four values and states explicitly
  that "restriction"/"exception" are override types, never deontic values;
- spells out override-target formatting: a bare same-regulation article number,
  never the article itself, a lid/subparagraaf, a whole afdeling, a maatwerk
  instrument, or another law's article (Bbl/Bal).

The few-shot set was left unchanged (the four leaking examples), so the A/B
isolates the instruction text.

### Re-run with the sharpened prompt

gpt-4o went from 6 to 5 mismatches. The movement matters more than the count.

Fixed, as intended: 22.1 now agrees (constitutive — the scope/precedence clause
rule worked) and 22.12 now agrees (obligation — the declarative
performance-requirement rule worked). Both targeted local errors landed.

22.19 improved but is still wrong: no longer constitutive (good), but now
permission instead of prohibition. The model took the conditional "is ...
toegestaan als ..." clause in one lid over the core prohibition in lid 1 — the
lid-granularity problem, not a prompt failure.

22.4 (empowerment) and 22.37 (modification) unchanged — ontology gaps.

Regression worth understanding: 22.38 was correct under the original prompt
(prohibition + 22.36:restriction) and is now exemption. 22.38 says "Artikel 22.36
is niet van toepassing op ...". Whether disapplying a target is an exemption or a
prohibition depends on the target's polarity: 22.36 is a permission
(vergunningvrij), so switching it off re-imposes the permit requirement — a
prohibition. The sharpened exemption cue ("is niet van toepassing op") was too
broad and tipped it the wrong way.

Decision: freeze the prompt here rather than keep tuning it against 38 gold items
(4 of them leaked), which would overfit. The remaining errors are all structural.

### Design: derive the override article's deontic, don't ask for it

The 22.38 case shows that an article which disapplies another cannot be tagged
from its own text; the result depends on the target article's polarity, which
lives elsewhere in the graph. The fix is to split the job:

- the LLM asserts only the local fact: this article disapplies that article, and
  whether it lifts the target (exception) or narrows it (restriction). gpt-4o
  already does this part reliably (it found 22.36:restriction both runs);
- the graph derives the net force from the target's base deontic, by deontic
  composition:
  - exception on a prohibition -> permission in the excepted scope,
  - exception on an obligation -> exemption,
  - restriction on a permission -> prohibition (this is 22.38),
  - restriction on an obligation -> a tightened obligation.

The combined labels (e.g. "restriction-on-permission") must be derived in the
graph, not emitted by the LLM — asking the model for the combined label
reintroduces the relational problem. The model emits the neutral operation plus
the target; the graph composes the rest. Costs: two phases (tag all base norms,
then resolve overrides); the net force is scope-conditional; some articles are
both a base norm and an override at once (22.28). Aligns with how LegalRuleML
models defeasibility. Implemented as `prototype/derive_overrides.cypher`.

### Graph-grounded use case: what the activity and location nodes carry

Building the "answer a real inquiry" visualization exposed what the graph can and
cannot say today.

Location does not discriminate. Every rule's `OP_LOCATIE` points at a single
`Locatie`, "Ambtsgebied gemeente Maastricht" — the whole municipality. There is
no sub-area node (no beschermd-stadsgezicht polygon) in this slice, so the graph
cannot say *where* a rule bites; spatial scope is uniform across all rules.

Activity is generic too. 22.36 (permission) governs the activity "Bouwactiviteit
(omgevingsplan)". Its restrictions 22.38 (cultureel erfgoed) and 22.39 (externe
veiligheid) govern the *same* generic activity. The cultural-heritage and
external-safety triggers live in the rule text ("... is niet van toepassing op
een activiteit die wordt verricht: ...") as conditions, not as separate
`Activiteit` or `Locatie` nodes.

Consequence: in v0 the graph answers "which rules apply to a building activity
and how they interact" (base permission plus OVERRIDES restrictions), but not
"does the restriction fire for *this* build". The firing conditions are
unmodelled text. Making them first-class (a Voorwaarde / Gebiedsaanwijzing node
for cultural heritage, external safety, monument) is the concrete v1 step, and
22.38 / 22.39 are the worked example.

Schema note for querying: an article links to its own rule text by
`IS_TEKST_VAN`, not `BEVAT` (`BEVAT` hops sideways to child/sibling articles).
The governing path is
`Artikel -IS_TEKST_VAN- Regeltekst -VAN_REGELTEKST- RegelVoorIedereen -GELDT_VOOR-> Activiteit`
(and `-OP_LOCATIE-> Locatie`). The use-case query in
`prototype/use_case_queries.cypher` traverses these three norm edges and
deliberately excludes `BEVAT` so each rule resolves to its own activity.

### The six mismatches (original prompt), adjudicated

Only two of the six are genuine model errors; the rest point at the labels or the
ontology.

22.12 (Aansluiting afvoer) — model wrong, gold right. "De gebouwaansluiting ...
is zodanig dat ... gehandhaafd blijft", "ligt ... haaks" are performance
requirements written as plain statements, i.e. obligations; the model read them
as description. (Fixed by the sharpened prompt.)

22.19 (Brandgevaarlijke stoffen) — model wrong, gold right. The core norm "Op een
open erf of terrein nabij een bouwwerk is geen brandgevaarlijke stof ... aanwezig"
is a prohibition written declaratively; the model fixated on the counting
convention and called the whole article constitutive. (Now prescriptive but
tagged permission — see re-run.)

22.16 (Overbewoning) — both defensible; a granularity problem. Lid 1 is a
prohibition, lid 2 an exemption for COA asylum housing. Gold tagged by the primary
norm; the model by the exemption lid.

22.1 (Voorrangsbepaling) — ontology gap: precedence. A conflict-resolution
meta-rule disapplying whole afdelingen. (The sharpened prompt made the single-tag
agree as constitutive.)

22.4 (Maatwerkvoorschriften) — ontology gap: empowerment. "Met een
maatwerkvoorschrift kan worden afgeweken van de artikelen in deze afdeling." A
power-conferring rule, neither a citizen-facing permission (gold) nor a
definition (model).

22.37 (Bijbehorend bouwwerk, bijzondere gevallen) — ontology gap: modification.
"... is Artikel 22.36 ... van overeenkomstige toepassing", "gelden in plaats van
de in Artikel 22.36 ... gestelde eisen de volgende eisen". A derogation /
modification class we have not built.

### What the disagreements mean

Four kinds:

Genuine model errors — declarative obligations and prohibitions read as
descriptions (22.12, and 22.11 in one run). Fixed by the sharpened prompt.

Annotation-unit problem — 22.16, 22.19: deontic force lives at the lid level.

Relational deontic — 22.38: an article that disapplies another cannot be tagged
from its own text; the result depends on the target's polarity. Handled by the
derived-override design above.

Ontology gaps — 22.1 (precedence), 22.4 (empowerment/maatwerk), 22.37
(modification).

### Schema violations under the original prompt

The full-graph run showed the model emitting values that are invalid under the
schema: a `deontic` of "restriction" (22.23), self-overrides (22.197, 22.250),
lid and subparagraaf override targets ("eerste lid", "22.2.7.3"), afdeling-level
targets (Afdeling 22.2/22.3) and cross-law targets (Bbl/Bal articles like
4.1057). The sharpened prompt now forbids these, but a prompt cannot reliably
enforce them, so they must also be enforced in code before anything is written to
Neo4j.

### The gold is a silver standard

`gold_deontic.csv` is single-annotator, labelled by us against the v0
definitions. There is no authoritative STOP/TPOD field for deontic force — that
is why we extract it. So "agreement" partly measures agreement between two
LLM-style reads, which inflates easy cases and makes hard-case disagreements
ambiguous. A trustworthy figure would need blind double annotation with the
ontology as the codebook and a reported inter-annotator agreement (Cohen's
kappa).

## Current issues

- The graph is tagged by the gpt-4o extractor (`deontic_source = openai:gpt-4o`),
  guarded and with write hygiene. The step-3 text validation did not confirm the
  tag errors a title-based pass suspected — on the articles checked, the tags are
  correct or defensible.
- Validation must read article text, not titles: a class of "omgevingsplan-
  activiteit X" articles are submission-requirement obligations that look like
  activity permits by their name.
- Missing v1 categories, surfaced by validation: assessment / decision rules
  (beoordelingsregels) and measurement conventions; modification ("overeen-
  komstige toepassing"); temporal / overgangsrecht.
- Override deontic is relational (22.38): handled by the derived-override pass
  (`derive_overrides.cypher`), which composes the net effect in the graph.
- Annotation unit is too coarse: several articles mix a primary norm with
  exemptions and measurement rules (22.16, 22.19, 22.146, 22.149). Article-level
  vs lid-level is an open decision.
- Firing conditions are unmodelled: location is uniform (whole municipality) and
  the heritage/safety triggers are textual, so the graph shows which rules can
  apply, not whether they fire for a given case.
- Gold set is a single-annotator silver standard with few-shot leakage; a
  defensible number needs held-out scoring and blind double annotation.
- Temperature-0 runs are not reproducible; report the spread, not one number.
