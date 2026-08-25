# Exercise demonstration media

## What is in place

`exercise_media` has existed since the first migration and was empty until now. The read
path — table → domain → DTO → API → mobile — is wired and covered by tests
(`tests/api/test_exercise_catalog.py::TestExerciseMedia`).

**217 of 274 exercises (79%) now carry two photographs each — 434 rows.**

## Source and licence

[yuhonas/free-exercise-db](https://github.com/yuhonas/free-exercise-db) — 873 exercises,
two photographs each, released under **The Unlicense**.

| | |
|---|---|
| Licence | The Unlicense (public domain) |
| Cost | none |
| Attribution | not required |
| Commercial use | permitted |
| Re-hosting | permitted |

Chosen over the alternatives on licence terms: wger's images are CC-BY-SA and carry a
share-alike obligation that would reach into our own content, and the animated-GIF APIs
(ExerciseDB and similar) are subscription-priced and generally forbid re-hosting.

## Running the import

```bash
# Dry run first — it reports coverage and never writes.
python -m coresync.infrastructure.seed.exercise_media --dry-run

# Apply.
python -m coresync.infrastructure.seed.exercise_media --apply
```

Re-running is idempotent: each matched exercise has its existing rows cleared before the
new ones are inserted, so the import never accumulates duplicate photographs.

## Why coverage is 79% and not 100%

Their catalogue and ours were written independently. Only 72 of our 274 movements have an
identically-named entry; a hand-checked alias table
(`ALIASES` in `exercise_media.py`) carries the rest to 217.

**The remaining 57 are deliberately left empty.** Closing that gap with fuzzy matching was
tried and rejected — token-similarity scoring pairs our *Barbell Row* with their *Barbell
Rear Delt Row* at maximum confidence, and *Bear Crawl* with *Bear Crawl Sled Drags*. Those
are different movements. Someone learning a lift copies what the picture shows, under
load, so a wrong demonstration is worse than none.

Every alias is validated at import time. One that stops resolving is reported as a
`broken_alias` rather than silently skipped, so an upstream rename cannot quietly empty a
row. Three of our movements (`overhead-carry`, `swimming`, `bird-dog`) have no plausible
counterpart at all and were dropped rather than pointed at a lookalike.

To extend coverage, add entries to `ALIASES` after checking the target by eye against the
source catalogue. The unmatched slugs are listed in the import report.

## Outstanding decisions

**1. Hosting.** URLs currently point at `raw.githubusercontent.com`. That works today and
is fine for development, but serving a production app off GitHub raw is fragile and
against the spirit of their bandwidth. The content is public domain, so mirroring is
explicitly permitted: copy `exercises/**` into object storage behind a CDN and re-run the
import with `--image-origin https://cdn.example.com/exercises`. Roughly 1,750 JPEGs.

**2. Video.** The schema's `media_type` already allows `video` and `animation`, and the
mobile viewer filters to what it can render, so adding video later needs no migration —
only a player (`expo-video`) and a source. No free, redistributable, comprehensive video
set was found; the realistic paths are a paid animated-GIF licence or producing our own.

## Mobile

- `ExerciseMediaViewer` — full-bleed 4:3 carousel with paging dots, on the exercise
  detail screen.
- `ExerciseThumbnail` / `ExerciseThumbnailButton` — 44pt square on picker rows, 36pt on
  active-workout exercise cards, tapping through to the detail screen.
- `expo-image` with `cachePolicy="memory-disk"`, so a demonstration opened repeatedly is
  fetched once. It also decodes animated WebP and GIF on both platforms, which is what
  makes the animation path a drop-in later.
- An exercise with no media renders a placeholder of exactly the same size, so rows do
  not shift as images arrive.
