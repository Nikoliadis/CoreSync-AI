# CoreSync AI

A production-grade fitness ecosystem: workout tracking, nutrition logging, body progress,
and an AI coach — on web, iOS and Android, backed by a single cloud API.

> **Status:** backend and web are built; mobile is in progress.
>
> | | State |
> |---|---|
> | **Backend** | Phases 0–5 complete. 124 endpoints, 57 tables, 13 migrations, 942 tests |
> | **Web** | Every screen except progress photos, meal planner and calendar. 86 tests |
> | **Mobile** | Foundation and the active workout. Nutrition, progress and coach are next |
> | **Workers** | Notification outbox and account erasure running on Celery beat |
>
> Not built yet: progress photos (no blob storage), meal planner, calendar, admin UI, web
> i18n, accessibility beyond the public routes, load testing, penetration testing, store
> submission. The blueprint is in `docs/`; the phased plan is in
> [docs/15-roadmap.md](docs/15-roadmap.md).

**Naming:** the product is *CoreSync AI*. In code, config and infrastructure the short
form `coresync` is used — Python package `coresync`, database `coresync`, API host
`api.coresync.ai`, deep-link scheme `coresync://`.

---

## What it is

The product as designed. The **Built** column is what exists today — the status block
above is the short version.

| Pillar | Comparable to | What CoreSync does | Built |
|---|---|---|---|
| Workout tracking | Strong, Hevy | Routines, live session logging, supersets, drop sets, rest timer, PR detection, history | ✅ |
| Nutrition tracking | MyFitnessPal | Food search, barcode scan, custom foods, recipes, macros + micronutrients, water | ✅ |
| AI coach | — | Context-aware chat, weekly reports, tool calling over the user's own data | ✅ chat and reports; no photo analysis |
| Achievements | — | Definitions, evaluation, streaks | ✅ |
| Adaptive training | Fitbod | Recovery-aware workout generation, progressive overload, plateau detection | ❌ |
| Social | Strava-lite | Follows, likes, challenges, leaderboards | ❌ out of MVP by design |

## Documentation map

Read in order. Each document is self-contained but assumes the previous ones.

| # | Document | Contents |
|---|---|---|
| 01 | [Product & Scope](docs/01-product-and-scope.md) | Personas, feature inventory, MVP cut, non-goals, success metrics |
| 02 | [System Architecture](docs/02-system-architecture.md) | C4 diagrams, components, request/data flows, architecture decision records |
| 03 | [Database Schema](docs/03-database-schema.md) | Full PostgreSQL model, ER diagrams per domain, every relationship explained, indexing, partitioning |
| 04 | [API Design](docs/04-api-design.md) | REST conventions, complete endpoint catalog, pagination, filtering, error contract, versioning |
| 05 | [Backend Architecture](docs/05-backend-architecture.md) | Clean Architecture layers, folder structure, repository + service + UoW patterns, DI, background jobs |
| 06 | [Authentication](docs/06-authentication.md) | Email/Google/Apple flows, JWT + refresh rotation, verification, reset, session revocation |
| 07 | [Web Frontend](docs/07-frontend-web.md) | Next.js App Router structure, data layer, state, forms, performance, SEO |
| 08 | [Mobile](docs/08-mobile.md) | Expo/React Native structure, offline-first sync, barcode scanning, notifications, store release |
| 09 | [Design System](docs/09-design-system.md) | Tokens, typography, colour, dark/light, components, motion, accessibility |
| 10 | [AI Architecture](docs/10-ai-architecture.md) | Context assembly, RAG, tool calling, vision pipeline, safety guardrails, cost control, evaluation |
| 11 | [Security](docs/11-security.md) | Threat model, OWASP controls, rate limiting, secrets, privacy, GDPR, data export/erasure |
| 12 | [DevOps & Deployment](docs/12-devops-deployment.md) | Docker, Compose, GitHub Actions, Azure topology, environments, migrations, observability |
| 13 | [Testing Strategy](docs/13-testing-strategy.md) | Test pyramid, pytest layout, fixtures, contract tests, E2E, load testing, quality gates |
| 14 | [Scalability & Operations](docs/14-scalability-and-operations.md) | Growth stages to millions of users, caching, read replicas, SLOs, runbooks, cost model |
| 15 | [Roadmap](docs/15-roadmap.md) | 8 phases, deliverables, team shape, estimates, risk register |

## Repository layout

```text
CoreSync/
├── backend/            # FastAPI API — Clean Architecture, Alembic migrations
├── frontend/           # Next.js web app (+ admin/)
├── mobile/             # Expo / React Native app
├── ai/                 # Prompts, evaluation sets, retrieval corpus (not runtime code)
├── database/           # Container init SQL and dev seeds
├── docker/             # Dockerfiles
├── nginx/              # Reverse proxy: TLS, HSTS, volumetric rate limits
├── docs/               # ← the blueprint (start here)
├── scripts/            # Operational scripts (+ azure/bicep infrastructure as code)
├── .github/workflows/  # CI/CD pipelines
└── docker-compose.yml  # Local development stack
```

Two boundaries in that tree are deliberate and easy to get wrong:

- **Alembic migrations live in `backend/migrations/`, not `database/`.** They import the
  SQLAlchemy models to resolve `target_metadata`, so they are code versioned with the code
  that depends on them. `database/` holds only SQL that runs *before* the application
  exists. See [database/README.md](database/README.md).
- **`ai/` holds content, not code.** The coach runs inside the API and reads user history
  through the same repositories as every other feature; a separate service would need its
  own copy of that data access for no benefit at this scale. What lives in `ai/` is the
  material that should be reviewable without reading Python — prompts, evaluation sets,
  knowledge sources. See [ai/README.md](ai/README.md).

## Tech stack

**Backend** — Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 (+ pgvector) · Redis · Celery · Pydantic v2

**Web** — Next.js 16 (App Router) · React 19 · TypeScript · Tailwind v4 · TanStack Query · Zustand · React Hook Form + Zod

**Mobile** — React Native 0.76 · Expo SDK 52 · Expo Router · TypeScript · TanStack Query · Zustand · expo-sqlite offline store · expo-secure-store

**AI** — Azure OpenAI (primary) behind a provider-agnostic gateway · pgvector for retrieval

**Cloud** — Azure App Service · Azure Database for PostgreSQL Flexible Server · Azure Cache for Redis · Azure Blob Storage + Front Door CDN · Key Vault · Application Insights · Vercel (web)

## Running it locally

The full stack in containers:

```bash
cp .env.example .env          # fill in secrets
docker compose up -d          # postgres, redis, api, worker, beat, mailhog, minio
docker compose exec api alembic upgrade head
docker compose exec api python -m coresync.infrastructure.seed.runner
```

Or run the services directly against containerised infrastructure, which is what most
day-to-day work looks like:

```bash
docker compose up -d postgres redis

cd backend
uv sync --all-extras --dev
uv run alembic upgrade head
uv run python -m coresync.infrastructure.seed.runner    # exercises, nutrients, foods
uv run uvicorn coresync.presentation.main:app --port 8000

cd ../frontend
npm install && npm run dev
```

| | |
|---|---|
| API docs | http://localhost:8000/docs |
| Web | http://localhost:3000 |

**Verifying an account in development.** Registration requires email verification and
there is no mail server unless you run the full Compose stack. The `ConsoleEmailSender`
prints the verification token to the API log — copy it from there. With Compose, MailHog
catches the mail instead, at http://localhost:8025.

### Mobile

```bash
cd mobile
npm install
npx expo start                # then press i / a, or scan with Expo Go
```

The app reads `EXPO_PUBLIC_API_URL`, defaulting to `http://localhost:8000`. A physical
device needs your machine's LAN address rather than localhost.

### Background workers

Scheduled work — draining the notification outbox, erasing accounts past their grace
period — needs both processes. Compose runs them; standalone they are:

```bash
cd backend
uv run celery -A coresync.infrastructure.worker.app worker -l info
uv run celery -A coresync.infrastructure.worker.app beat -l info      # exactly one
```

## Conventions

- **Units:** the database stores canonical SI (kg, cm, ml, kcal, grams). Conversion to
  lb/in/fl-oz happens at the presentation layer only.
- **Identifiers:** UUIDv7 primary keys everywhere — time-ordered, index-friendly, safe to expose.
- **Timestamps:** `timestamptz` in UTC. "Days" that matter to the user (diary dates, streaks) are
  stored as `date` in the *user's* timezone, computed at write time.
- **Money & measurements:** `numeric`, never `float`.
- **Offline writes:** the mobile client mints UUIDv7 ids before a write leaves the device,
  so a replayed sync is idempotent — the same primary key arrives twice and the second is
  a no-op rather than a duplicate set.
- **Energy reconciliation:** stored calories must agree with the macros that imply them,
  counting alcohol at 7 kcal/g alongside the usual 4/4/9. A database constraint enforces
  it, because a food that reports half the calories it contains is worse than no food at
  all.

## Licence

Proprietary. All rights reserved.
