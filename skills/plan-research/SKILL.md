---
name: plan-research
description: Turn a research question into bounded multilingual queries and a reviewable ResearchPlan before any source discovery begins.
metadata:
  version: "1.0.0"
---

# Plan research

Produce a bounded plan that preserves the user's question, constraints, source kinds, and budget. The caller validates the invocation against `input.schema.json`; return exactly one JSON object matching `output.schema.json`.

## Process

1. Normalize the question without changing its meaning. Keep explicit inclusion, exclusion, date, language, source, and seed constraints.
2. Use `search_library` only to identify already-covered terminology or duplicate scope. Treat summaries as context, not evidence for new claims.
3. Propose focused Chinese and English query expansions. Explain each expansion and label it as an inference until a human approves it.
4. Put the proposed plan and queries in both `structured` and a concise `markdown` preview.
5. Call `request_human_review` with gate `plan_confirmation`, then end the turn. Source discovery starts only in a later run state carrying approval.

## Evidence and warnings

Every substantive statement gets an `evidence` record. Use `supported` only with real `source#chunk-N` anchors, `inference` for reasoned proposals, and `rejected` for claims that should not proceed. Copy all anchors from supported records into top-level `evidence_ids`. Record ambiguity, missing constraints, and budget pressure in `warnings`.

## Tool boundary

The complete tool surface is `search_library` and `request_human_review`. All other inputs arrive through the validated invocation object; all outputs leave through the validated output object.

The package fixture and expected behavior are maintained in `examples/case.json` and `EXPECTED.md`.
