# Enrichment — System Alignment Contract

What the engine reads when you build your own **client profile** and **formats**. Everything below is now honored (nothing silently dropped). Verification (Reoon/ESP) stays a separate step and is untouched.

## Where each piece goes (config fields)

| You build | Save it as | What it drives |
|-----------|-----------|----------------|
| Client profile | `profile` (object) | The writer's understanding of your offer |
| ICP / Non-ICP rules | `icp_definition` (string or JSON) | The ICP/Non-ICP gate |
| Variables / formats | `formats` (array) — `variables` also accepted | What copy gets written, and how |
| Global writing rules | `rules` (text, one per line) | Applied to every variable |

## Client profile — ALL fields pass through now

Put whatever you want. Every key reaches the writer (bounded in size). Metadata keys (`profile_version`, `website`, ids, timestamps) are skipped. So your old-style keys all work:

`client_name, service_brief, main_offer, what_we_are_pitching, target_outcome, problems_we_solve, customer_challenges, results_we_bring, what_we_do, icp_summary, icp, non_icp, positioning, proof_points, case_studies, global_rules, …` — all used.

## A variable (in `formats` / `variables`) — every rich field is now used

```json
{
  "name": "personalized_first_line",
  "label": "Personalized First Line",
  "type": "text",                       // or "classification"
  "allowed_values": ["ICP","Non-ICP"],  // classification only
  "purpose": "…what this variable is for…",
  "core_formula": {
    "primary": "[Specific company asset] + [Observation] + [Positive implication]",
    "examples": ["…", "…"]
  },
  "research_priority_order": [
    {"priority": 1, "type": "Flagship product/framework", "why": "…", "examples": ["…"]},
    {"priority": 2, "type": "Unique differentiator", "why": "…", "examples": ["…"]}
  ],
  "ideal_length": {"min_words": 8, "recommended_words": "12-22", "max_words": 28},
  "instructions": ["…", "…"],
  "rules": ["…"],
  "examples": ["good example 1", "…"],           // up to 5 fed to the model
  "rejected_examples": [{"text": "…", "reason": "why it's bad"}],  // up to 3
  "min_words": 8, "max_words": 28
}
```

- `core_formula` → the line is built on that shape.
- `research_priority_order` → personalizes on the highest-priority asset actually found on the site.
- `instructions` → every one is followed.
- `examples` / `rejected_examples` → teach style; the last 5 / 3 reach the model.

## ICP definition (`icp_definition`)

Structured is recommended (extra keys like `mode`/`note` are fine now):

```json
{
  "procedure": ["step 1", "step 2"],
  "icp_categories": ["marketing/SEO/growth agencies", "…"],
  "hard_non_icp": ["public pricing shown", "consumer/self-serve SaaS", "…"],
  "default": "Non-ICP",
  "note": "optional extra context"
}
```

Plain prose also works — it's handed to the classifier verbatim.

## Model + humanizer (env vars in Railway)

- `WRITER_MODEL` = `gpt-4o` (writing) · `EXTRACT_MODEL` = `gpt-4o` for deeper facts (default is `gpt-4o-mini` for cost).
- `HUMANIZE_PASS` = `1` turns on the extra humanizer pass (keeps every specific fact; off by default).
- Human voice is baked into every generation regardless of the flag.
