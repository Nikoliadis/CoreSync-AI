# Evaluations

A health-adjacent assistant needs a regression suite for the same reason the API does: a
prompt change that improves tone can quietly break a safety rule, and nobody notices until
a user is harmed.

## Structure

| Path | Contents |
|---|---|
| `safety/` | Cases that must **never** pass. Calorie floors, injury deflection, disordered-eating patterns. A failure here blocks release |
| `grounding/` | Cases with known logged data and a known correct answer, to catch invented history |
| `quality/` | Graded cases for tone and usefulness. Regressions here are reviewed, not blocking |

## Why safety cases are separate

They are a different kind of test. A grounding failure is a bug; a safety failure is an
incident. Keeping them in one bucket means the pass rate averages the two together and a
safety regression hides behind good numbers elsewhere.

## Status

Not implemented. Phase 5 builds this alongside the coach, and the roadmap treats the
evaluation set as a deliverable rather than something added afterwards — a prompt with no
regression suite cannot be changed safely.
