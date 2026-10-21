// Derive each OVERRIDES edge's net effect from the target's deontic.
//
// Prerequisite: the graph is tagged (build_and_tag.cypher or
// deontic_extract.py --write), so articles carry `deontic` and OVERRIDES edges
// exist. Run in Neo4j Browser one block at a time, or headless:
//   cypher-shell -a <bolt-url> -u <user> -p <password> < cypher/derive_overrides.cypher   (my exact command: ../local-setup.md)
//
// Why: an article that disapplies another cannot be tagged from its own text —
// the net force depends on what the target is. The LLM is reliable at the local
// fact (which article is disapplied, and whether it is lifted = exception or
// narrowed = restriction), but not at composing the net force. So we compose it
// here, deterministically, from the override type and the target's deontic.
//
// Composition (LegalRuleML-style defeasibility):
//   exception   on prohibition -> permission   (the forbidden thing is allowed in the carve-out)
//   exception   on obligation  -> exemption    (no longer obliged in the carve-out)
//   restriction on permission  -> prohibition  (allowed thing needs a permit again; 22.38 on 22.36)
//   restriction on exemption   -> prohibition  (the lifted base rule is reimposed; 22.28 on 22.27)
//   restriction on obligation  -> obligation   (a tightened duty)
//   restriction on prohibition -> prohibition  (a narrowed ban)
// Other combinations are left null (not a defined legal move here).


// 1. Annotate every OVERRIDES edge with the target's deontic and the derived
//    effect. Safe to re-run.
MATCH (:Artikel)-[o:OVERRIDES]->(tgt:Artikel)
SET o.target_deontic = tgt.deontic,
    o.derived_effect = CASE o.override_type + '|' + coalesce(tgt.deontic, '')
      WHEN 'exception|prohibition'   THEN 'permission'
      WHEN 'exception|obligation'    THEN 'exemption'
      WHEN 'restriction|permission'  THEN 'prohibition'
      WHEN 'restriction|exemption'   THEN 'prohibition'
      WHEN 'restriction|obligation'  THEN 'obligation'
      WHEN 'restriction|prohibition' THEN 'prohibition'
      ELSE null
    END;


// 2. Report the cases the derivation corrects: an overriding article whose own
//    (LLM) deontic differs from the derived effect of its override. agrees=false
//    is where the graph composition disagrees with the per-article tag — e.g.
//    22.38 (restriction on a permission -> prohibition) if the LLM said exemption.
MATCH (src:Artikel)-[o:OVERRIDES]->(tgt:Artikel)
WHERE o.derived_effect IS NOT NULL
RETURN src.nummer AS artikel, src.deontic AS llm_force,
       o.override_type AS op, tgt.nummer AS target, o.target_deontic AS target_force,
       o.derived_effect AS derived,
       src.deontic = o.derived_effect AS agrees
ORDER BY agrees, artikel;


// 3. Full override table with the derived effect, for inspection / retrieval.
MATCH (src:Artikel)-[o:OVERRIDES]->(tgt:Artikel)
RETURN src.nummer AS artikel, o.override_type AS op, tgt.nummer AS target,
       o.target_deontic AS target_force, o.derived_effect AS derived_effect
ORDER BY artikel;
