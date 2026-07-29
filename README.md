# CoreSync AI

A production-grade fitness ecosystem: workout tracking, nutrition logging, body progress,
and an AI coach — on web, iOS and Android, backed by a single cloud API.

> **Status:** Phase 2 (Workout Tracking) — API complete. Exercise catalog, routines, live
> session logging, personal records, history and the offline `/sync` contract are
> implemented and tested; the offline-first mobile client is not yet built. The complete
> technical blueprint lives in `docs/`; the phased delivery plan is in
> [docs/15-roadmap.md](docs/15-roadmap.md).

**Naming:** the product is *CoreSync AI*. In code, config and infrastructure the short
form `coresync` is used — Python package `coresync`, database `coresync`, API host
`api.coresync.ai`, deep-link scheme `coresync://`.

---

## What it is

| Pillar | Comparable to | What CoreSync does |
|---|---|---|
| Workout tracking | Strong, Hevy | Routines, live session logging, supersets, drop sets, rest timer, PR detection, history |
| Nutrition tracking | MyFitnessPal | Food search, barcode scan, custom foods, recipes, macros + micronutrients, water |
| Adaptive training | Fitbod | Recovery-aware workout generation, progressive overload, plateau detection |
| AI coach | — | Context-aware chat, weekly/monthly reports, meal & training plans, progress-photo analysis |
| Social | Strava-lite | Follows, likes, achievements, challenges, leaderboards |

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
├── apps/
│   ├── api/            # FastAPI backend (Clean Architecture)
│   ├── web/            # Next.js 15 web app
│   ├── mobile/         # Expo / React Native app
│   └── admin/          # Admin panel (Next.js route group or separate app)
├── packages/
│   ├── shared-types/   # OpenAPI-generated TS types shared by web + mobile
│   ├── ui/             # Cross-platform design tokens & primitives
│   └── config/         # Shared eslint / tsconfig / tailwind presets
├── infra/
│   ├── docker/         # Dockerfiles
│   ├── bicep/          # Azure infrastructure as code
│   └── scripts/        # Operational scripts
├── docs/               # ← the blueprint (start here)
├── .github/workflows/  # CI/CD pipelines
└── docker-compose.yml  # Local development stack
```

## Tech stack

**Backend** — Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 (+ pgvector) · Redis · Celery · Pydantic v2

**Web** — Next.js 15 (App Router) · React 19 · TypeScript · TailwindCSS · TanStack Query · Zustand

**Mobile** — React Native · Expo (dev client) · NativeWind · TanStack Query · MMKV/SQLite offline store

**AI** — Azure OpenAI (primary) behind a provider-agnostic gateway · pgvector for retrieval

**Cloud** — Azure App Service · Azure Database for PostgreSQL Flexible Server · Azure Cache for Redis · Azure Blob Storage + Front Door CDN · Key Vault · Application Insights · Vercel (web)

## Local development (target state)

```bash
cp .env.example .env          # fill in secrets
docker compose up -d          # postgres, redis, api, worker, beat, mailhog, minio
docker compose exec api alembic upgrade head
docker compose exec api python -m coresync.infrastructure.seed.runner   # exercise catalog
# API      → http://localhost:8000/docs
# Web      → http://localhost:3000
```

## Conventions

- **Units:** the database stores canonical SI (kg, cm, ml, kcal, grams). Conversion to
  lb/in/fl-oz happens at the presentation layer only.
- **Identifiers:** UUIDv7 primary keys everywhere — time-ordered, index-friendly, safe to expose.
- **Timestamps:** `timestamptz` in UTC. "Days" that matter to the user (diary dates, streaks) are
  stored as `date` in the *user's* timezone, computed at write time.
- **Money & measurements:** `numeric`, never `float`.

## Licence

Proprietary. All rights reserved.
