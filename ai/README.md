# AI assets

Prompts, evaluation sets and the retrieval corpus for the AI coach. Architecture and
model-routing design: [docs/10 · AI Architecture](../docs/10-ai-architecture.md).

## The boundary

**Runtime code lives in `backend/`, not here.** The coach is part of the API, not a
separate service:

- `backend/src/coresync/domain/coaching/` — ports (`LLMGateway`) and rules
- `backend/src/coresync/application/ai/` — use cases
- `backend/src/coresync/infrastructure/ai/` — provider adapters, model router, cost metering

That is not incidental. The coach reads a user's training and nutrition history through
the same repositories as every other feature, and the architecture contracts in
`backend/pyproject.toml` enforce that it depends inward like anything else. A separate
service would need its own copy of that data access, or an internal API over it, for no
benefit at this scale (docs/02 §9).

What belongs *here* is everything that is **content rather than code** — the material that
should be reviewable, diffable and editable without touching Python:

| Path | Contents |
|---|---|
| `prompts/` | System prompts and tool descriptions, versioned |
| `evaluations/` | Golden datasets and graded outputs for the eval loop |
| `knowledge/` | Source documents for the retrieval corpus, chunked and embedded into `ai_embeddings` |

## Why prompts are files, not string literals

A safety instruction buried in a Python f-string is invisible to the person who needs to
review it, and a change to it looks like a code change in the diff. Keeping prompts as
files means the eating-disorder safety rules in `prompts/coach-system.md` can be read by
someone who does not write Python, and a change to them shows up as a change to them.

## Safety is layered, and prompts are the weakest layer

Prompt instructions are the *last* line, not the first. The calorie floor is enforced by
`ck_nutrition_targets_calorie_floor` on the table, then by `TdeeCalculator`, then by
service-layer validation, and only then by the prompt. A prompt can be talked out of a
rule; a `CHECK` constraint cannot (docs/10 §7).

## Status

Phase 5 of [the roadmap](../docs/15-roadmap.md). Not implemented — the prompts here are
the design artefact, and the model routing, cost metering and retrieval pipeline they
assume do not exist yet.
