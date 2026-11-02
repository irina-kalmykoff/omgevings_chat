# Knowledge Graph — Ontology v0 (minimal), with a v1 draft

Group 2 — Knowledge Graphs for Reliable Legal RAG

The smallest ontology that lets us label rules and test items consistently. It
is deliberately minimal and co-evolves with the test set: every concept here is
exercised by a real rule in the Maastricht omgevingsplan, and nothing is added
speculatively. See `knowledge-graph-next-steps-plan.md` (step 1) and
`project-plan-presentation-feedback.md` (points 1–2).

Sections 1–7 are v0, the version built into the graph today. Section 8 is the v1
draft (2026-10-23): a tested proposal for the override relation, not yet in the
extractor or the graph. Section 8.9 (2026-11-02) adds candidates from four new
use cases.

## Principles

- **LegalRuleML is the backbone** (deontic operators + defeasibility/override).
  LKIF-Core lends a few class names; ELI lends identifiers. STOP/TPOD already
  gives identity, document structure, activity and area, so those are reused,
  not re-modelled.
- **Minimal and earned.** Only concepts a real rule needs. New concepts go to
  v1 only when a test item cannot be labelled without them.
- **Deontic is the point.** The one thing our raw graph lacked — the normative
  force of a rule and the exception relations between rules — is what v0 adds.

## 1. Classes

| v0 class | Neo4j label (now) | STOP/TPOD · IMOW | Legal ontology |
|---|---|---|---|
| LegalSource | Regeling, Afdeling, Paragraaf, Subparagraaf, Artikel, Lid | document structure | ELI LegalResource; AKN subdivision |
| Norm | Regeltekst, RegelVoorIedereen | juridische regel | LKIF Norm; LegalRuleML Statement |
| Activity | Activiteit | Activiteit | LKIF Action |
| Location | Locatie, ambtsgebied | Locatie, Gebiedsaanwijzing | spatial scope (applies-in-area) |

## 2. Statement type and deontic tag

Every **Norm** has a `statement_type`:

- **prescriptive** — a rule that regulates behaviour (carries a deontic tag).
- **constitutive** — a definition or "counts-as" statement (no deontic force);
  e.g. article 1.1 Begripsbepalingen.

A **prescriptive** Norm carries one `deontic` tag:

| Tag | Meaning | Dutch cues | Example (gm0935) |
|---|---|---|---|
| obligation | must do / must provide | moet, is verplicht, worden verstrekt | 22.35 (aanvraagvereisten) |
| prohibition | must not / permit required | het is verboden, mag niet, vergunningplicht | 22.26 (vergunning OPA bouwwerken) |
| permission | may / allowed / permit-free | mag, is toegestaan, vergunningvrij, van rechtswege in overeenstemming | 22.36 (vergunningvrij van rechtswege) |
| exemption | lifts an obligation/prohibition for stated cases | geldt niet voor, is niet van toepassing, niet vereist | 22.27 (uitzonderingen op 22.26) |

A rule that *re-imposes* a base rule by cancelling an exemption (e.g. 22.28, 22.38
"is niet van toepassing" for monuments) is tagged by its **effect** — here
`prohibition` — and expressed with an `OVERRIDES` edge of type `restriction`
(section 3).

`deontic_source` records provenance of the tag: `stop_annotation` |
`llm_extraction` | `manual`.

## 3. Relations

| Relation | Meaning | Neo4j edge (now) | Legal ontology |
|---|---|---|---|
| CONTAINS | structural containment | BEVAT | AKN structure |
| HAS_NORM | a source component carries a norm | IS_TEKST_VAN (inverse) | — |
| GOVERNS_ACTIVITY | the norm regulates an activity | GELDT_VOOR | LKIF Action |
| APPLIES_IN | the norm applies in an area | OP_LOCATIE | spatial scope |
| OVERRIDES | this norm defeats/qualifies another | VERWIJST_NAAR (force-bearing subset) | LegalRuleML override / defeasibility |
| REFERS_TO | plain cross-reference, no force | VERWIJST_NAAR (remainder) | — |

The key refinement over the raw graph: the single `VERWIJST_NAAR` cross-reference
splits into **OVERRIDES** (carries deontic force — an exception or restriction)
and **REFERS_TO** (a plain pointer). `OVERRIDES` has an `override_type`:
`exception` (lifts the base) or `restriction` (reinstates the base).

## 4. How it maps onto the Neo4j property graph

No new database; v0 is labels and properties on what exists.

- On each **Norm** node (Regeltekst / RegelVoorIedereen): add `statement_type`,
  `deontic`, `deontic_source`.
- Split **VERWIJST_NAAR**: where the referencing text carries force
  ("geldt niet", "is niet van toepassing", "onverminderd"), relabel/annotate as
  `OVERRIDES` with `override_type`; otherwise it stays `REFERS_TO`.
- `GOVERNS_ACTIVITY`, `APPLIES_IN`, `HAS_NORM`, `CONTAINS` are the existing
  edges, renamed only in documentation.

## 5. Worked examples in v0

**Dakkapel chain (22.26 → 22.27 → 22.28):**

- 22.26 Norm, prescriptive, `prohibition` (permit required to build).
- 22.27 Norm, prescriptive, `exemption`; `OVERRIDES(exception)` → 22.26.
- 22.28 Norm, prescriptive, `prohibition`; `OVERRIDES(restriction)` → 22.27
  (the exemption is lifted for monuments → permit required again).

**Permit-free chain (22.36 → 22.38 / 22.39):**

- 22.36 Norm, prescriptive, `permission` (permit-free of right).
- 22.38 Norm, prescriptive, `prohibition`; `OVERRIDES(restriction)` → 22.36
  (not permit-free for cultural heritage).
- 22.39 Norm, prescriptive, `prohibition`; `OVERRIDES(restriction)` → 22.36
  (not permit-free in external-safety A/B zones).

**Definition (1.1):** Norm, `constitutive`, no deontic tag.

## 6. Deontic tagging precedence

1. STOP/TPOD annotation where the standard encodes it.
2. Otherwise LLM extraction keyed on the Dutch cues in section 2.
3. Manual correction during the ten-location validation and test-set review.

Record which was used in `deontic_source` so coverage and reliability are
reportable.

## 7. Deferred to v1 (added only when a test item needs it)

- Conditional permission/obligation ("mag, mits …", "tenzij …") as a first-class
  condition rather than free text. *Still open.*
- External-source references (a rule pointing to the Bbl/Bal/Bkl national law) as
  a typed cross-document link. *Addressed by the v1 draft (section 8.4).*
- Temporal validity (overgangsrecht, in-/uitwerkingtreding dates). *Partly
  addressed: a `temporal` flag on derogations (section 8.3); a standalone
  temporal concept is still open.*
- Agent / addressee (here almost always "iedereen", so omitted in v0). *Partly
  addressed: the authority as actor of a discretionary derogation (section 8.2).*

## 8. v1 draft — the override relation (2026-10-23)

Status: proposal, tested with `scripts/derogation_probe.py` on 35 "in afwijking
van" articles plus 15 controls (three rounds, two runs each); not yet in
`deontic_extract.py` or `derive_overrides.cypher`. Evidence: findings
2026-10-23 ("Derogation flavor probe and a v1 override proposal").

### 8.1 Why v0 is not enough

v0 asks the LLM for `exception` or `restriction`. Two things go wrong:

- **The LLM cannot see the target's polarity.** Whether disapplying an article
  lifts a duty (exception) or reinstates one (restriction) depends on what the
  target is, which lives elsewhere in the graph. Even canonical 22.28 ("Artikel
  22.27 niet van toepassing") is labelled exception from its own text.
- **"In afwijking van" is not one concept.** Across 35 articles it covers six
  legal functions: derogation inside the same article, modification of another
  article's values, grandfathering, eerbiedigende-werking scope clauses,
  decision-authority derogation, and derogation from national law or a standard.
  These mix three independent questions: what the clause does, where its target
  is, and whether it concerns an existing situation.

### 8.2 Split of work: LLM proposes, rules check, graph composes

The LLM states only the **local operation** that the clause's own text shows:

| `operation` | Meaning | Dutch cues | Example |
|---|---|---|---|
| disapply | the target rule, or part of it, does not apply to the stated cases, or applies only to some | geldt niet voor, is niet van toepassing, hoeft niet, is alleen van toepassing voor zover, mag ... in afwijking van | 22.27 → 22.26; 22.28 → 22.27 |
| modification | the target keeps applying to the same cases, but its content changes: values, limits, distances, deadlines, method | gelden in plaats van ... de volgende eisen; is ... niet hoger dan [other value] | 22.64 / 22.65 / 22.66 → 22.63 (other noise values) |
| discretionary | the competent authority may decide differently from what the target prescribes | kan het bevoegd gezag; kan de omgevingsvergunning toch worden verleend | 22.32, 22.33, 22.278 |

Narrowing or widening *when* or *to whom* a rule applies is `disapply`, not
`modification`. `discretionary` requires an authority as actor (section 8.5).
Permissive derogation ("mag, in afwijking van") was tested and dropped as a
separate operation: it is `disapply` plus the temporal flag.

The **graph** then derives the v0 override type and the net effect from the
operation and the target's deontic (extends `derive_overrides.cypher`):

| operation | target deontic | override_type (derived) | derived_effect |
|---|---|---|---|
| disapply | obligation | exception | exemption |
| disapply | prohibition | exception | exemption |
| disapply | permission | restriction | prohibition |
| disapply | exemption | restriction | the base the exemption lifted (follow its own OVERRIDES edge); prohibition if unknown |
| disapply | constitutive (scope clause) | scope | none (scope of the target narrows) |
| modification | any | modification | the target's deontic, with changed content |
| discretionary | any | empowerment | undetermined: depends on a decision of the authority |

`discretionary` is the one operation whose effect the graph cannot compose: the
answer to "may I?" becomes "only if the authority decides so". This also covers
the empowerment gap of v0 (22.4, 22.34, 22.45: maatwerk and permit conditions),
so one concept closes both.

### 8.3 Edge attributes

Every OVERRIDES edge carries, besides `operation`, `override_type` and
`derived_effect`:

- `target_scope`: `same_article` (a lid or onderdeel of the same article),
  `other_article` (another article of this regulation), `external` (Bal/Bbl
  article or a standard such as NEN-EN 1825).
- `temporal`: true when the clause depends on an existing or earlier situation,
  a date, or eerbiedigende werking / overgangsrecht.
- `quote`: the decisive words, for provenance and review.
- `operation_source`: provenance as for `deontic_source` (llm_extraction, manual).

### 8.4 Graph additions

- **Same-article derogations** become `Lid -[:OVERRIDES]-> Lid` edges between
  existing `Lid` nodes (`Artikel -BEVAT-> Lid`). The deontic tag stays at article
  level; no rebuild of the annotation unit is needed for these.
- **External targets** get an `ExternalSource` node (national-law article or
  standard, identified by its citation), linked by `OVERRIDES` with
  `target_scope = external`. Today the guards drop these targets.

### 8.5 Deterministic checks

- **Schema guards** extended to the new fields: `operation`, `target_scope` and
  `derived_effect` only take the listed values (the probe saw
  `net_effect = "restriction"` 4 times in its first round).
- **Actor guard**: `discretionary` is kept only when the quoted clause names an
  authority or a decision (bevoegd gezag, college, (omgevings)vergunning,
  maatwerk, besluit); otherwise it becomes `disapply`. A prompt-only actor test
  failed on passive "kan ... worden" clauses (22.148, 22.198, 22.204); the guard
  gave perfect precision on all three probe rounds.
- **Temporal**: not yet stable (flips on 22.90, 22.218, 22.59 between runs); needs
  a cue list (eerbiedigende werking, "voor [datum]", bestaande / rechtmatig
  aanwezig) or the same lexical-guard treatment.

### 8.6 Evidence so far

| Check | Result |
|---|---|
| target scope separable | same-article 22/23, external 7/8, other-article as expected |
| modification precision (round 2) | 17/17 clauses keep the target's obligation; 0 in controls |
| discretionary after actor guard | only decision-authority clauses kept (6/10, 8/14, 8/14) |
| operation stability | 49/50 articles identical across runs |
| schema violations (rounds 2–3) | 0 |

### 8.7 Open before adoption

- Temporal flag stability (section 8.5).
- Composition at scale: tested on 2026-11-01 over all 38 edges of the rebuilt
  graph (findings). The rule holds wherever its inputs are right; the 18
  disagreeing or undefined edges trace to the categories of this draft, plus
  measurement conventions and scope clauses read as overrides. Multi-hop chains
  compose correctly step by step; one target with conflicting overrides (22.29)
  needs firing conditions.
- Mixed-lid articles: the discharge-route template ("kan worden geloosd in X ...
  wordt niet geloosd in Y") and obligation + exemption-lid articles are where all
  remaining tag disagreements sit (silver v2: clean 100%, flagged 64%).
- Firing conditions (mits / tenzij, heritage and safety triggers), assessment
  rules, precedence / voorrang: still outside v1.
- Integration: add `operation`, `target_scope`, `temporal` to the extractor
  output, the actor guard to `sanitize_prediction`, and the table in 8.2 to
  `derive_overrides.cypher`.

### 8.8 Legal-ontology alignment

- `disapply` / `exception` / `restriction`: LegalRuleML overrides and
  defeasibility, as in v0.
- `modification`: a derogation in the sense of legislative modification (the
  target stays in force with altered content), as in Akoma Ntoso's modification
  metadata.
- `discretionary`: a power-conferring rule (Hohfeldian power) rather than a
  deontic operator; the authority is the addressee.

### 8.9 Candidates from four use cases (2026-11-02)

Source: 34 articles read blind on 2026-11-01 (labels and notes in
`artikelen_labels_2026-11-01.csv`), afterwards revealed as four use cases built
around a DSO activity, like the dakkapel and permit-free chains:

| Case | Articles | Question it answers |
|---|---|---|
| Odour from wastewater treatment plants | 22.121–22.124 | How much odour may a treatment plant cause near homes? |
| Noise from activities | 22.62–22.74 | How much noise may an activity cause at a noise-sensitive building? |
| Noise from roads and railways | 22.271–22.276 | Do I need a permit to build or change a road? |
| Odour from livestock | 22.96–22.105 | May a farm keep more animals near homes? |

Agreed with the case owner: candidates C1–C3 go into this v1 draft; C4–C5 stay
with the external-source and firing-condition work. Status: proposals, not yet
tested.

**C1. Measurement rules with deontic effect (noise case).** 22.70 lid 1–2,
22.65 / 22.66 lid 3 and 22.72 lid 1 never say a rule does not apply; they say
certain noise "blijft buiten beschouwing" when the level is determined. Formally
a convention (constitutive), in effect an exemption for those sources. Proposal:
the article keeps `statement_type = constitutive`, and the relation to the norms
it measures becomes an OVERRIDES edge with `operation = disapply` and
`mechanism = measurement`, so the composition yields an exemption for the
excluded sources without retagging the article.

**C2. Norms relative to a past state: standstill (livestock and treatment-plant
cases).** 22.99, 22.102 lid 2, 22.104, 22.105 and 22.124 set no value of their
own: "mag niet toenemen", "niet hoger dan voorafgaand aan de verandering". The
reference point is an earlier situation of the activity. The `temporal` flag
marks the grandfathering but not this norm. Proposal: a norm attribute
`baseline` (e.g. `prior_state`) with the reference moment ("onmiddellijk voor de
inwerkingtreding van de Omgevingswet", "voorafgaand aan de verandering"). The
graph cannot evaluate such a norm without facts about the case; it can say that
the answer depends on the historical situation. 22.124 is the clearest example:
gpt-4o tags it as an obligation without OVERRIDES, while it bounds the
grandfathering of 22.122 lid 2 and 22.123 (blind label: obligation, restriction
on 22.123, low confidence).

**C3. Two schema extensions.**

- **Override of a convention** (livestock case): 22.103 lid 2 measures the
  distance from the facade instead of the emission point set in 22.97. The
  composition table in 8.2 covers modifications of norms only. Proposal: add
  `modification` on a constitutive target, with `derived_effect = none` and the
  meaning "changes how the norms that use this convention are measured".
- **Range and paragraph targets** (noise case): "22.63 tot en met 22.71" (22.73,
  22.70) and "deze paragraaf" (22.62a). Today these are dropped or forced into
  single-article edges. Proposal: allow `Paragraaf` / `Subparagraaf` nodes as
  targets, and expand an explicit range into one edge per article, keeping the
  quoted range as provenance (`target_range`). The guards must accept both.

**Parked with other work.**

- C4. Norm content delegated to another instrument (22.67 values from an older
  municipal ordinance, 22.73 festive days set by ordinance, 22.62 lid 2
  maatwerk): with the `ExternalSource` node of 8.4, extended from override
  target to content source.
- C5. Zones defined by geometry (22.273 aandachtsgebied, 200–600 m from the road
  axis): with the firing-condition and spatial work.

**First cases for gaps already listed:** cumulation ("onverminderd 22.98 tot en
met 22.102" in 22.103); conjunctive and reasonableness conditions (22.70 lid 3,
22.73); a temporary rule (22.62a); rules addressed to the authority (22.275,
22.276).

**Side finding:** 22.99 lid 2 refers to "de waarde, bedoeld in Artikel 22.96",
but 22.96 is the scope clause; 22.98 seems meant. Possibly a drafting error in
the plan itself (confirmed as worth noting by the case owner).

## Provenance

Snapshot: Omgevingsplan gemeente Maastricht (gm0935), expression @34, 2026-10.
Identifiers: AKN/FRBR as delivered in the STOP package
(`/akn/nl/act/gm0935/2020/omgevingsplan`).
