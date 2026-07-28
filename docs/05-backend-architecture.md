# 05 · Backend Architecture

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 · Alembic · Celery.
Clean Architecture with four layers and one rule.

---

## 1. The dependency rule

```
        presentation  ──▶  application  ──▶  domain  ◀──  infrastructure
           (HTTP)          (use cases)      (rules)        (adapters)
```

**Dependencies point inward. Nothing points out of `domain`.**

| Layer | Knows about | Must never import |
|---|---|---|
| `domain` | Nothing but Python and other domain code | FastAPI, SQLAlchemy, Redis, `httpx`, Azure SDKs, Pydantic models used for HTTP |
| `application` | `domain` | FastAPI, SQLAlchemy, any concrete adapter |
| `infrastructure` | `domain`, `application` (to implement their ports) | `presentation` |
| `presentation` | `application`, `core` | SQLAlchemy models, repository implementations |

This is enforced mechanically, not by discipline — see §9.

**Why bother.** Three concrete payoffs, all of which we need:

1. **The AI provider, the storage backend and the push service are replaceable.** They are
   adapters behind ports. Swapping Azure OpenAI for Anthropic is one new file.
2. **Business rules are testable without infrastructure.** PR detection, macro calculation, and
   plateau detection are pure functions over domain objects — no database, no event loop,
   milliseconds per test. ~70 % of the suite runs this way.
3. **The module seams are where services would be extracted.** ADR-001 defers microservices;
   this structure is what makes that deferral cheap to reverse.

---

## 2. Folder structure

```text
apps/api/
├── pyproject.toml                # uv/poetry, ruff, mypy, pytest config
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── src/coresync/
│   │
│   ├── core/                     # cross-cutting, framework-light
│   │   ├── config.py             # pydantic-settings; the only place os.environ is read
│   │   ├── security.py           # password hashing, JWT encode/decode, token hashing
│   │   ├── errors.py             # exception hierarchy + error-code registry
│   │   ├── logging.py            # structlog: JSON, request-id, user-id, PII redaction
│   │   ├── pagination.py         # cursor encode/decode/sign
│   │   ├── units.py              # canonical-unit conversion helpers
│   │   ├── ids.py                # UUIDv7 generation
│   │   └── types.py              # Money, Weight, Kcal value types; Result/Either
│   │
│   ├── domain/                   # ← zero external dependencies
│   │   ├── shared/
│   │   │   ├── entity.py         # Entity, AggregateRoot, DomainEvent bases
│   │   │   ├── value_objects.py  # Weight, Reps, Rpe, Macros, DateRange
│   │   │   └── exceptions.py     # DomainError hierarchy
│   │   ├── identity/
│   │   │   ├── entities.py       # User, AuthIdentity, RefreshToken
│   │   │   ├── policies.py       # password policy, lockout policy
│   │   │   └── repositories.py   # UserRepository (Protocol) ← port
│   │   ├── profile/
│   │   │   ├── entities.py       # Profile, NutritionTarget, Goal
│   │   │   ├── services.py       # TdeeCalculator, MacroSplitter  ← pure business rules
│   │   │   └── repositories.py
│   │   ├── workout/
│   │   │   ├── entities.py       # Routine, WorkoutSession, SessionSet, PersonalRecord
│   │   │   ├── services.py       # PersonalRecordDetector, VolumeCalculator, OneRepMax
│   │   │   ├── events.py         # WorkoutCompleted, PersonalRecordAchieved
│   │   │   └── repositories.py
│   │   ├── exercise/
│   │   ├── nutrition/
│   │   │   ├── entities.py       # Food, DiaryEntry, Recipe
│   │   │   ├── services.py       # MacroCalculator, ServingResolver
│   │   │   └── repositories.py
│   │   ├── progress/
│   │   │   ├── entities.py       # WeightLog, BodyMeasurement, ProgressPhoto
│   │   │   ├── services.py       # TrendSmoother (EWMA), PlateauDetector
│   │   │   └── repositories.py
│   │   ├── coaching/
│   │   │   ├── entities.py       # Conversation, Message, Insight, CoachContext
│   │   │   ├── policies.py       # SafetyPolicy: calorie floors, medical-claim rules
│   │   │   └── ports.py          # LLMGateway, EmbeddingGateway, VisionGateway ← ports
│   │   ├── social/
│   │   └── billing/
│   │       └── entities.py       # Subscription, Entitlement
│   │
│   ├── application/              # use cases; orchestration only, no business rules
│   │   ├── common/
│   │   │   ├── unit_of_work.py   # UnitOfWork Protocol
│   │   │   ├── dto.py            # input/output DTOs (dataclasses, not HTTP schemas)
│   │   │   ├── event_bus.py      # in-process domain-event dispatch
│   │   │   └── decorators.py     # @transactional, @cached, @rate_limited
│   │   ├── identity/
│   │   │   ├── register_user.py
│   │   │   ├── authenticate_user.py
│   │   │   ├── rotate_refresh_token.py
│   │   │   └── oauth_sign_in.py
│   │   ├── workout/
│   │   │   ├── start_session.py
│   │   │   ├── log_set.py
│   │   │   ├── complete_session.py
│   │   │   └── sync_offline_batch.py
│   │   ├── nutrition/
│   │   ├── progress/
│   │   ├── coaching/
│   │   │   ├── context_assembler.py
│   │   │   ├── chat.py
│   │   │   ├── generate_weekly_report.py
│   │   │   └── detect_plateaus.py
│   │   └── billing/
│   │       └── entitlements.py
│   │
│   ├── infrastructure/
│   │   ├── database/
│   │   │   ├── session.py        # async engine, sessionmaker, replica routing
│   │   │   ├── base.py           # DeclarativeBase, mixins
│   │   │   ├── models/           # SQLAlchemy ORM models, one module per domain
│   │   │   ├── repositories/     # concrete repositories implementing domain ports
│   │   │   ├── mappers/          # ORM model ⇄ domain entity
│   │   │   └── unit_of_work.py   # SqlAlchemyUnitOfWork
│   │   ├── cache/
│   │   │   ├── redis_client.py
│   │   │   ├── cache_service.py
│   │   │   └── locks.py          # distributed locks
│   │   ├── storage/
│   │   │   ├── azure_blob.py
│   │   │   ├── s3_compat.py      # local dev / MinIO
│   │   │   └── image_processor.py# EXIF strip, resize, format conversion
│   │   ├── ai/
│   │   │   ├── gateway.py        # LLMGateway implementation + routing/fallback
│   │   │   ├── providers/        # azure_openai.py, openai.py, anthropic.py, fake.py
│   │   │   ├── prompts/          # versioned prompt templates (*.jinja + metadata)
│   │   │   ├── tools/            # tool definitions + executors
│   │   │   ├── embeddings.py
│   │   │   └── guardrails.py     # input/output filters, schema validation
│   │   ├── external/
│   │   │   ├── openfoodfacts.py
│   │   │   ├── usda_fdc.py
│   │   │   ├── google_oidc.py
│   │   │   └── apple_oidc.py
│   │   ├── notifications/
│   │   │   ├── email/            # SMTP / Azure Communication Services + templates
│   │   │   ├── push/             # Expo / APNs / FCM
│   │   │   └── outbox.py         # transactional outbox dispatcher
│   │   └── tasks/
│   │       ├── celery_app.py
│   │       ├── schedules.py      # beat schedule
│   │       ├── ai_tasks.py
│   │       ├── media_tasks.py
│   │       ├── report_tasks.py
│   │       ├── notification_tasks.py
│   │       └── maintenance_tasks.py
│   │
│   ├── presentation/
│   │   ├── main.py               # app factory, lifespan, router registration
│   │   ├── dependencies.py       # FastAPI DI: current_user, uow, services
│   │   ├── middleware/
│   │   │   ├── request_context.py# request id, timing, structured access log
│   │   │   ├── rate_limit.py
│   │   │   ├── error_handler.py  # domain exception → HTTP problem response
│   │   │   └── security_headers.py
│   │   ├── schemas/              # Pydantic v2 request/response models (camelCase alias)
│   │   └── api/v1/
│   │       ├── auth.py  users.py  exercises.py  routines.py  sessions.py
│   │       ├── nutrition.py  progress.py  ai.py  social.py
│   │       ├── notifications.py  admin.py  system.py
│   │       └── router.py
│   │
│   └── cli.py                    # seed, backfill, reconcile, admin utilities
└── tests/
    ├── unit/                     # domain + application, no I/O
    ├── integration/              # repositories, real Postgres via testcontainers
    ├── api/                      # httpx AsyncClient against the app
    ├── contract/                 # schemathesis over the OpenAPI spec
    └── factories/                # polyfactory builders
```

---

## 3. Domain layer — pure rules

Business logic lives here as plain Python, with no framework in sight.

```python
# domain/workout/services.py
from dataclasses import dataclass
from decimal import Decimal
from coresync.domain.workout.entities import SessionSet, PersonalRecord, RecordType


@dataclass(frozen=True)
class DetectedRecord:
    record_type: RecordType
    value: Decimal
    set_id: UUID
    previous_value: Decimal | None


class PersonalRecordDetector:
    """Decides which sets in a completed session beat the user's existing records.

    Pure: takes the sets and the current records, returns what changed. No database,
    no clock, no I/O — so every edge case is a fast unit test.
    """

    # Warm-ups are practice, not performance. Including them would inflate every PR.
    EXCLUDED_SET_TYPES = frozenset({"warmup"})

    def detect(
        self,
        sets: Sequence[SessionSet],
        current: Mapping[RecordType, PersonalRecord],
    ) -> list[DetectedRecord]:
        working = [s for s in sets if s.set_type not in self.EXCLUDED_SET_TYPES and s.is_completed]
        if not working:
            return []

        candidates: list[DetectedRecord] = []
        for record_type, extract in self._EXTRACTORS.items():
            best = max((extract(s) for s in working if extract(s) is not None), default=None)
            if best is None:
                continue
            existing = current.get(record_type)
            if existing is None or best > existing.value:
                candidates.append(
                    DetectedRecord(record_type, best, ..., existing.value if existing else None)
                )
        return candidates

    @staticmethod
    def estimated_one_rep_max(weight: Decimal, reps: int) -> Decimal | None:
        """Epley. Deliberately capped at 15 reps — the formula diverges from reality
        beyond that, and a 'PR' derived from a 30-rep set is noise, not progress."""
        if reps <= 0 or reps > 15:
            return None
        return (weight * (1 + Decimal(reps) / 30)).quantize(Decimal("0.01"))
```

```python
# domain/profile/services.py
class TdeeCalculator:
    """Mifflin-St Jeor BMR × activity multiplier, then goal adjustment.

    Every constant here is a documented, reviewable business decision — not a magic
    number buried in a service method.
    """

    ACTIVITY_MULTIPLIERS = {
        "sedentary": Decimal("1.2"), "light": Decimal("1.375"),
        "moderate": Decimal("1.55"), "active": Decimal("1.725"),
        "very_active": Decimal("1.9"),
    }
    # Conservative on purpose: aggressive deficits are the main way fitness apps hurt people.
    GOAL_ADJUSTMENT_PCT = {
        "lose_fat": Decimal("-0.18"), "maintain": Decimal("0"),
        "gain_muscle": Decimal("0.10"), "recomp": Decimal("-0.05"),
    }
    ABSOLUTE_CALORIE_FLOOR = {"male": 1500, "female": 1200}   # mirrors the DB CHECK

    def calculate(self, profile: Profile, weight_kg: Decimal, goal: Goal) -> NutritionTarget:
        bmr = self._mifflin_st_jeor(profile, weight_kg)
        tdee = bmr * self.ACTIVITY_MULTIPLIERS[profile.activity_level]
        target = tdee * (1 + self.GOAL_ADJUSTMENT_PCT[goal.goal_type])

        floor = self.ABSOLUTE_CALORIE_FLOOR.get(profile.gender, 1200)
        target = max(target, Decimal(floor))       # never below the floor, whatever the maths says

        protein_g = weight_kg * (Decimal("2.2") if goal.goal_type != "maintain" else Decimal("1.8"))
        fat_g = (target * Decimal("0.25")) / 9
        carbs_g = (target - protein_g * 4 - fat_g * 9) / 4
        return NutritionTarget(calories=target, protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)
```

**Ports** are declared where they are needed — in the domain — and implemented outside it:

```python
# domain/workout/repositories.py
class WorkoutSessionRepository(Protocol):
    async def get(self, session_id: UUID, user_id: UUID) -> WorkoutSession | None: ...
    async def get_active(self, user_id: UUID) -> WorkoutSession | None: ...
    async def add(self, session: WorkoutSession) -> None: ...
    async def list_history(
        self, user_id: UUID, cursor: Cursor | None, limit: int
    ) -> Page[WorkoutSession]: ...

# domain/coaching/ports.py
class LLMGateway(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]: ...
```

Note that `user_id` is a parameter on every repository read. **Authorisation is a data-access
concern, not an afterthought** — there is no `get(session_id)` overload that could accidentally
return another user's workout.

---

## 4. Application layer — use cases

One class per use case. It orchestrates: load, invoke domain rules, persist, emit events. It
contains no business rules of its own.

```python
# application/workout/complete_session.py
@dataclass(frozen=True)
class CompleteSessionCommand:
    user_id: UUID
    session_id: UUID
    perceived_effort: int | None = None


@dataclass(frozen=True)
class CompleteSessionResult:
    session: WorkoutSessionDTO
    new_records: list[PersonalRecordDTO]


class CompleteSessionUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        pr_detector: PersonalRecordDetector,
        volume_calculator: VolumeCalculator,
        events: EventBus,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._pr_detector = pr_detector
        self._volume = volume_calculator
        self._events = events
        self._clock = clock

    async def execute(self, cmd: CompleteSessionCommand) -> CompleteSessionResult:
        async with self._uow:
            session = await self._uow.sessions.get(cmd.session_id, cmd.user_id)
            if session is None:
                raise NotFoundError("workout_session", cmd.session_id)
            if session.status is not SessionStatus.IN_PROGRESS:
                raise ConflictError("session_already_completed")

            session.complete(at=self._clock.now(), perceived_effort=cmd.perceived_effort)
            session.total_volume_kg = self._volume.total(session.all_sets)

            current = await self._uow.records.current_for_exercises(
                cmd.user_id, session.exercise_ids
            )
            detected = self._pr_detector.detect(session.all_sets, current)
            records = [PersonalRecord.from_detection(d, cmd.user_id) for d in detected]
            await self._uow.records.supersede_and_add(records)

            await self._uow.summaries.apply_workout(session)   # incremental aggregate update
            await self._uow.streaks.register_workout(cmd.user_id, session.local_date)

            # Committed atomically with the domain write — the outbox pattern. A crash
            # after commit cannot lose the follow-up work, and a rollback cannot leak it.
            await self._uow.commit()

        await self._events.publish(
            WorkoutCompleted(user_id=cmd.user_id, session_id=session.id,
                             new_record_count=len(records))
        )
        return CompleteSessionResult(
            session=WorkoutSessionDTO.from_entity(session),
            new_records=[PersonalRecordDTO.from_entity(r) for r in records],
        )
```

**Unit of Work** gives one transaction per use case and one place to get repositories:

```python
# infrastructure/database/unit_of_work.py
class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self.sessions  = SqlAlchemyWorkoutSessionRepository(self._session)
        self.records   = SqlAlchemyPersonalRecordRepository(self._session)
        self.summaries = SqlAlchemySummaryRepository(self._session)
        self.streaks   = SqlAlchemyStreakRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            await self._session.rollback()      # rollback is the default, not the exception
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
```

---

## 5. Infrastructure — adapters

### 5.1 Repository implementation with a mapper

ORM models and domain entities are **separate types**. The ORM model serves persistence
(columns, relationships, lazy loading); the entity serves business rules. A mapper translates.

```python
# infrastructure/database/repositories/workout.py
class SqlAlchemyWorkoutSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: UUID, user_id: UUID) -> WorkoutSession | None:
        stmt = (
            select(WorkoutSessionModel)
            .where(
                WorkoutSessionModel.id == session_id,
                WorkoutSessionModel.user_id == user_id,      # ← ownership in the query
                WorkoutSessionModel.deleted_at.is_(None),
            )
            .options(
                selectinload(WorkoutSessionModel.exercises)
                .selectinload(SessionExerciseModel.sets)
            )
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return WorkoutSessionMapper.to_entity(model) if model else None
```

`selectinload` rather than `joinedload` for one-to-many: it issues a second query instead of
producing a cartesian product across sets, which is far cheaper for a session with 30 sets.

**Is the mapper worth the boilerplate?** For `identity`, `workout`, `nutrition`, `progress` and
`coaching` — yes; these carry real rules and benefit from framework-free entities. For thin
CRUD (reference tables, admin) the repository returns Pydantic DTOs directly. Uniformity is not
worth 400 lines of pointless translation.

### 5.2 LLM gateway with routing and fallback

```python
# infrastructure/ai/gateway.py
class RoutingLLMGateway(LLMGateway):
    """Chooses a model per task class, meters cost, and fails over between providers."""

    ROUTING = {
        TaskClass.CLASSIFICATION:  ModelSpec("gpt-4o-mini", max_tokens=256),
        TaskClass.CHAT:            ModelSpec("gpt-4o",      max_tokens=1200),
        TaskClass.REPORT:          ModelSpec("gpt-4o",      max_tokens=3000),
        TaskClass.VISION:          ModelSpec("gpt-4o",      max_tokens=1500),
    }

    def __init__(self, providers: Sequence[LLMProvider], usage: UsageRecorder,
                 breaker: CircuitBreaker) -> None: ...

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        spec = self.ROUTING[request.task_class]
        last_error: Exception | None = None
        for provider in self._providers:                 # primary, then fallback
            if self._breaker.is_open(provider.name):
                continue
            try:
                response = await provider.complete(request, spec)
            except (ProviderTimeout, ProviderUnavailable) as exc:
                self._breaker.record_failure(provider.name)
                last_error = exc
                continue
            self._breaker.record_success(provider.name)
            await self._usage.record(request.user_id, provider.name, spec, response.usage)
            return response
        raise UpstreamUnavailableError("all_llm_providers_failed") from last_error
```

### 5.3 Celery task boundaries

Tasks are thin: resolve dependencies, call a use case, let the use case do the work.

```python
# infrastructure/tasks/report_tasks.py
@celery_app.task(
    bind=True, queue="ai", max_retries=3,
    autoretry_for=(UpstreamUnavailableError,),
    retry_backoff=30, retry_backoff_max=900, retry_jitter=True,
    acks_late=True, reject_on_worker_lost=True,   # long AI jobs must survive a worker restart
)
def generate_weekly_report(self, user_id: str) -> None:
    asyncio.run(_generate_weekly_report(UUID(user_id)))


async def _generate_weekly_report(user_id: UUID) -> None:
    async with container.scope() as scope:
        use_case = await scope.get(GenerateWeeklyReportUseCase)
        await use_case.execute(GenerateWeeklyReportCommand(user_id=user_id))
```

| Queue | Tasks | Concurrency | Notes |
|---|---|---|---|
| `default` | email, outbox dispatch, cache warm, summary reconciliation | high | must stay drained |
| `ai` | chat side-effects, insights, reports, plan generation, embeddings | low, cost-capped | rate-limited to protect the Azure OpenAI quota |
| `media` | EXIF strip, resize, thumbnails, exports | memory-bound | separate workers with a higher memory limit |

Scheduled (beat, all timezone-aware — a 7 a.m. reminder must be 7 a.m. *for that user*):

| Schedule | Task |
|---|---|
| every 1 min | `dispatch_notification_outbox` |
| every 5 min | `process_due_notification_schedules` |
| hourly | `refresh_food_search_popularity`, `expire_stale_sessions` |
| daily 03:00 UTC | `reconcile_daily_summaries`, `purge_expired_tokens`, `reap_orphan_blobs` |
| daily 04:00 UTC | `detect_plateaus`, `generate_daily_insights` |
| Mondays 06:00 local | `generate_weekly_reports` (fanned out per user timezone) |
| 1st of month | `generate_monthly_reports` |
| weekly | `import_openfoodfacts_delta`, `recompute_exercise_statistics` |

---

## 6. Presentation layer

Routers are thin. Validate, delegate, serialise.

```python
# presentation/api/v1/sessions.py
router = APIRouter(prefix="/workouts/sessions", tags=["workouts"])


@router.post(
    "/{session_id}/complete",
    response_model=CompleteSessionResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Complete a workout session",
)
async def complete_session(
    session_id: UUID,
    body: CompleteSessionRequest,
    user: CurrentUser = Depends(get_current_user),
    use_case: CompleteSessionUseCase = Depends(Provide[CompleteSessionUseCase]),
    _: None = Depends(idempotent),
) -> CompleteSessionResponse:
    result = await use_case.execute(
        CompleteSessionCommand(
            user_id=user.id, session_id=session_id, perceived_effort=body.perceived_effort
        )
    )
    return CompleteSessionResponse.from_result(result)
```

Domain exceptions become HTTP responses in exactly one place:

```python
# presentation/middleware/error_handler.py
EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404, ConflictError: 409, ForbiddenError: 403,
    ValidationError: 400, QuotaExceededError: 402, UpstreamUnavailableError: 503,
}


async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
    if status_code >= 500:
        logger.exception("unhandled_domain_error", error_code=exc.code)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": exc.code, "message": exc.user_message,
                           "requestId": request.state.request_id, "details": exc.details}},
    )
```

Use cases raise meaning; the HTTP layer decides status codes. No `HTTPException` below
`presentation/` — that would couple business logic to a web framework.

---

## 7. Dependency injection

FastAPI's `Depends` handles request-scoped wiring; a small container (`dependency-injector` or
hand-rolled) composes the object graph once at startup so that Celery workers and the CLI get
the same wiring without importing FastAPI.

```python
# presentation/dependencies.py
async def get_uow() -> AsyncIterator[UnitOfWork]:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    cache: CacheService = Depends(get_cache),
) -> CurrentUser:
    payload = decode_access_token(token)          # raises UnauthenticatedError
    if await cache.exists(f"revoked:{payload.jti}"):
        raise UnauthenticatedError("token_revoked")
    user = await cache.get_or_set(
        f"user:{payload.sub}:auth", ttl=300, factory=lambda: users.get_auth_view(payload.sub)
    )
    if user is None or user.status != "active":
        raise UnauthenticatedError("user_inactive")
    return user


RequireVerifiedEmail = Annotated[CurrentUser, Depends(require_verified_email)]
RequirePro          = Annotated[CurrentUser, Depends(require_entitlement("ai_unlimited"))]
RequireAdmin        = Annotated[CurrentUser, Depends(require_role("admin"))]
```

The auth view is cached for 5 minutes to keep the hot path off the database, and revocation
works through a Redis `revoked:{jti}` set — so a logout takes effect immediately even though the
JWT itself is still cryptographically valid.

---

## 8. Cross-cutting concerns

### Configuration
`pydantic-settings`, one `Settings` object, validated at startup — the process refuses to boot
with a missing or malformed secret rather than failing on the first request that needs it. No
module reads `os.environ` directly. In Azure, values arrive as Key Vault references.

### Logging
`structlog`, JSON in deployed environments. Every line carries `request_id`, `user_id`, `route`,
`duration_ms`. A redaction processor strips passwords, tokens, and — importantly — AI message
bodies and food-diary contents from logs by default.

### Observability
OpenTelemetry auto-instrumentation for FastAPI, SQLAlchemy, Redis and `httpx`, exported to
Application Insights. Custom spans around LLM calls carry model, token counts and cost as
attributes, so cost is queryable per endpoint and per user cohort.

### Health
`/health` is liveness only and touches nothing. `/health/ready` checks Postgres and Redis with a
250 ms timeout. Conflating them causes a slow dependency to trigger a restart storm.

---

## 9. Enforcing the architecture

Conventions that are not enforced decay. These run in CI:

```toml
# pyproject.toml
[tool.importlinter]
root_package = "coresync"

[[tool.importlinter.contracts]]
name = "Clean Architecture layers"
type = "layers"
layers = ["coresync.presentation", "coresync.application", "coresync.domain"]

[[tool.importlinter.contracts]]
name = "Domain is framework-free"
type = "forbidden"
source_modules = ["coresync.domain"]
forbidden_modules = ["fastapi", "sqlalchemy", "redis", "httpx", "celery", "azure"]

[[tool.importlinter.contracts]]
name = "Domain modules are independent"
type = "independence"
modules = [
    "coresync.domain.identity", "coresync.domain.workout",
    "coresync.domain.nutrition", "coresync.domain.progress",
    "coresync.domain.coaching", "coresync.domain.social",
]
```

Plus: `ruff` (with `flake8-bandit`, `flake8-async`), `mypy --strict` on `domain/` and
`application/`, and a custom check that no module under `presentation/` imports from
`infrastructure/database/models`.

The **independence** contract is the interesting one: it forbids `workout` from importing
`nutrition` directly. Cross-domain interaction goes through the application layer or domain
events. That is precisely what keeps the modules extractable into services later.

---

## 10. Performance notes

| Concern | Approach |
|---|---|
| N+1 queries | `selectinload` on collections; a test fixture asserts a query-count budget per endpoint and fails the build if it regresses |
| Connection pool | `pool_size=20`, `max_overflow=10` per instance, sized against the Postgres `max_connections` budget across all replicas + workers. PgBouncer in transaction mode once instance count exceeds ~10 |
| Statement timeout | 15 s server-side; 5 s on user-facing read paths |
| Serialisation | `orjson` response class — measurably faster on the large session and diary payloads |
| Bulk writes | `insert().on_conflict_do_update()` for the sync endpoint; never a loop of ORM adds |
| Slow endpoints | p95 tracked per route; a regression beyond budget fails the nightly load test |

---

**Next:** [06 · Authentication](06-authentication.md)
