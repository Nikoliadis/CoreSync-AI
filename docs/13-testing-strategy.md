# 13 · Testing Strategy

---

## 1. Shape of the suite

```
             ▲  E2E (Playwright, Detox)          ~40 tests    slow, brittle, high value
            ╱ ╲
           ╱   ╲  API / contract tests           ~250 tests
          ╱     ╲
         ╱       ╲  Integration (real Postgres)  ~400 tests
        ╱         ╲
       ╱___________╲  Unit (domain + application) ~1,400 tests  fast, cheap, precise
```

Roughly 70 % unit, 20 % integration, 8 % API, 2 % E2E. The Clean Architecture layering
([05](05-backend-architecture.md)) is what makes that ratio achievable — business rules are pure
functions, so the tests that cover the risky logic are also the fast ones.

**What we optimise for:** a full unit run in under 30 seconds locally, and a complete PR pipeline
in under 10 minutes. A suite slower than that gets skipped, and a skipped suite is worthless.

---

## 2. Coverage targets

| Area | Target | Rationale |
|---|---|---|
| `domain/` | **95 %** | Pure logic, no excuse. PR detection, macro maths, safety limits |
| `application/` | 90 % | Use-case orchestration |
| `infrastructure/repositories/` | 80 % | Covered by integration tests |
| `presentation/` | 75 % | Thin; covered by API tests |
| Overall gate | **80 %**, no decrease allowed | |

Coverage is a floor, not a goal. 100 % coverage of trivial getters proves nothing; a well-chosen
test of the PR-detection edge cases is worth a hundred of them. Reviews check the *cases*, not
the percentage.

---

## 3. Unit tests

No database, no network, no event loop where avoidable. Time is injected via a `Clock` protocol
so nothing depends on the wall clock.

```python
# tests/unit/domain/workout/test_personal_record_detector.py
class TestPersonalRecordDetector:
    def test_warmup_sets_never_count_toward_records(self) -> None:
        sets = [
            make_set(set_type="warmup", weight=200, reps=1),   # absurd on purpose
            make_set(set_type="normal", weight=100, reps=8),
        ]
        detected = PersonalRecordDetector().detect(sets, current={})
        assert all(d.value < 200 for d in detected)

    def test_estimated_1rm_is_none_above_fifteen_reps(self) -> None:
        # Epley diverges badly at high reps; a "PR" from a 30-rep set is noise.
        assert PersonalRecordDetector.estimated_one_rep_max(Decimal("60"), 30) is None

    @pytest.mark.parametrize("reps,expected", [(1, "100.00"), (5, "116.67"), (10, "133.33")])
    def test_epley_formula(self, reps: int, expected: str) -> None:
        assert PersonalRecordDetector.estimated_one_rep_max(Decimal("100"), reps) \
               == Decimal(expected)

    def test_ties_do_not_create_a_new_record(self) -> None:
        # Equalling a PR is not beating it. This is the bug users notice immediately.
        current = {RecordType.MAX_WEIGHT: make_record(RecordType.MAX_WEIGHT, Decimal("100"))}
        detected = PersonalRecordDetector().detect(
            [make_set(weight=100, reps=5)], current=current
        )
        assert detected == []
```

**Safety-critical logic gets property-based tests**, because the failure mode is a person eating
1,000 kcal a day:

```python
# tests/unit/domain/profile/test_tdee_calculator.py
@given(
    weight=st.decimals(min_value=35, max_value=250, places=1),
    height=st.integers(min_value=130, max_value=220),
    age=st.integers(min_value=13, max_value=100),
    activity=st.sampled_from(list(TdeeCalculator.ACTIVITY_MULTIPLIERS)),
    goal=st.sampled_from(list(TdeeCalculator.GOAL_ADJUSTMENT_PCT)),
)
def test_calorie_target_never_falls_below_the_safety_floor(weight, height, age, activity, goal):
    """No combination of legal inputs may produce an unsafe target.

    Hypothesis explores the space we would not think to enumerate by hand — which is
    exactly where a safety violation would hide.
    """
    target = TdeeCalculator().calculate(
        make_profile(height=height, age=age, activity_level=activity), weight, make_goal(goal)
    )
    assert target.calories >= 1200
    assert target.protein_g <= weight * 3          # ceiling from the safety table
    assert target.protein_g * 4 + target.fat_g * 9 <= target.calories
```

---

## 4. Integration tests

Real PostgreSQL via `testcontainers` — never SQLite. SQLite lacks the constraints, types,
partial indexes, generated columns and transactional semantics this schema depends on; a suite
that passes against SQLite and fails in production is worse than no suite.

```python
# tests/integration/conftest.py
@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        run_migrations(pg.get_connection_url())        # migrations are tested by running them
        yield pg


@pytest.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    """Each test runs inside a transaction that is rolled back afterwards.

    Fast (no re-seeding) and perfectly isolated, so tests can run in parallel.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        yield session
        await session.close()
        await trans.rollback()
```

What integration tests must cover, because unit tests structurally cannot:

- **Constraints actually fire.** `ck_targets_calorie_floor`, the partial unique indexes, the
  one-in-progress-session index.
- **Ownership scoping.** Every repository read is tested with a second user's id and must
  return nothing.
- **Cascade behaviour.** Deleting a routine must *not* delete sessions; deleting a user must
  cascade everywhere it should.
- **Incremental aggregates agree with batch recomputation.** A dedicated test writes a month of
  activity, then asserts `reconcile_summaries` produces identical numbers.
- **Query-count budgets.** A fixture counts emitted statements per endpoint and fails on
  regression — this is how N+1 problems get caught before production.

---

## 5. API tests

`httpx.AsyncClient` against the real app with dependency overrides for external services only.

```python
# tests/api/test_workout_flow.py
async def test_completing_a_session_detects_prs_and_updates_the_streak(client, auth_user):
    session = await start_session(client, routine_id=None)
    await log_set(client, session["id"], exercise="bench-press", weight=100, reps=8)
    await log_set(client, session["id"], exercise="bench-press", weight=105, reps=6)

    res = await client.post(f"/v1/workouts/sessions/{session['id']}/complete",
                            headers={"Idempotency-Key": str(uuid7())})
    assert res.status_code == 200
    body = res.json()
    assert len(body["newPersonalRecords"]) > 0
    assert body["totalVolumeKg"] == pytest.approx(1430.0)

    stats = (await client.get("/v1/progress/stats/overview")).json()
    assert stats["workoutStreak"]["current"] == 1


async def test_idempotency_key_prevents_duplicate_completion(client, auth_user):
    session = await start_completed_session(client)
    key = str(uuid7())
    first  = await client.post(f"/v1/workouts/sessions/{session['id']}/complete",
                               headers={"Idempotency-Key": key})
    second = await client.post(f"/v1/workouts/sessions/{session['id']}/complete",
                               headers={"Idempotency-Key": key})
    assert second.status_code == first.status_code
    assert second.json() == first.json()
    assert second.headers["Idempotency-Replayed"] == "true"
```

### The IDOR suite (blocks merge)

```python
# tests/api/test_authorization.py
@pytest.mark.parametrize("method,path_template", ALL_AUTHENTICATED_ENDPOINTS)
async def test_no_endpoint_exposes_another_users_resource(
    client, user_a, user_b, method, path_template
):
    """Generated from the OpenAPI spec, so a NEW endpoint is covered automatically.

    This is the structural defence against OWASP A01 — the risk that actually
    materialises in apps of this shape.
    """
    resource_id = await seed_resource_for(user_b, path_template)
    res = await client.request(
        method, path_template.format(id=resource_id), headers=auth(user_a)
    )
    assert res.status_code in (403, 404)
    assert str(resource_id) not in res.text        # not even leaked in an error message
```

Because it is parameterised from the spec, adding an endpoint without ownership scoping fails CI
on the first run. That is the property we want — security by construction, verified mechanically.

### Contract tests
Schemathesis fuzzes every endpoint from the OpenAPI schema: malformed payloads, boundary values,
wrong types, missing fields. It reliably finds unhandled 500s that hand-written tests miss.

---

## 6. Frontend & mobile

| Layer | Tool | Scope |
|---|---|---|
| Unit | Vitest / Jest | Unit conversion, 1RM, formatters, date/timezone helpers, reducers |
| Component | Testing Library | Behaviour via role/label queries — never by class name or test id where a role exists |
| Integration | MSW (handlers generated from the OpenAPI spec) | Feature flows against a mocked API that cannot drift |
| Offline | Jest + in-memory SQLite | **The sync engine gets its own dedicated suite** |
| E2E web | Playwright | Chromium + WebKit |
| E2E mobile | Maestro / Detox | iOS + Android on EAS |
| Visual | Playwright screenshots | Design-system components, both themes |
| A11y | axe-core | Every route, blocking |

**The offline sync engine is the most-tested client code in the product**, because its failures
are silent and destroy user data:

```ts
describe('sync engine', () => {
  it('replays the queue exactly once when the same batch is sent twice', async () => { … });
  it('preserves client order across a partial failure', async () => { … });
  it('resolves a concurrent edit by server-clamped timestamp', async () => { … });
  it('keeps a delete winning over a stale edit', async () => { … });
  it('survives an app kill mid-flush without losing an operation', async () => { … });
  it('backs off exponentially and never spins on a permanent rejection', async () => { … });
});
```

### E2E scope
Deliberately small — only journeys whose breakage would be catastrophic:

1. Register → verify → onboard → targets calculated.
2. Start workout → log sets → rest timer → complete → PR shown.
3. Search food → log to breakfast → totals and remaining update.
4. Log weight → chart renders the trend.
5. Upload progress photo → appears in the timeline.
6. Ask the AI coach → receive a grounded, streaming answer.
7. Login → logout → tokens invalidated.
8. Export data → download; delete account → data gone.

E2E tests run against an ephemeral environment with seeded data, on merge to `main` and nightly.
They are not run per-PR — too slow, too flaky, and the API tests already cover the logic.

---

## 7. AI testing

Covered in depth in [10](10-ai-architecture.md) §8. Summary of the gates:

| Suite | Gate |
|---|---|
| Safety (ED language, medical, injection, minors) | **100 % — blocks deploy** |
| Grounding (no hallucinated numbers) | ≥ 95 % |
| Tool selection | ≥ 90 % |
| Insight precision | ≥ 85 % |
| Plan structural validity | 100 % |

Deterministic components — context assembly, calculators, guardrails, the tool executor — are
tested as ordinary code with a **fake LLM provider** that returns scripted responses. Only the
eval suites call a real model, and they run on prompt/model changes rather than on every PR.

---

## 8. Performance testing

**k6**, nightly against staging, with the production data shape.

| Scenario | Load | Gate |
|---|---|---|
| Set logging burst | 500 concurrent sessions, 1 set/2 s | p95 < 150 ms |
| Food search | 200 rps | p95 < 150 ms |
| Diary read | 300 rps | p95 < 200 ms |
| Dashboard | 100 rps | p95 < 300 ms |
| Offline sync flood | 50 clients × 200 operations | p95 < 2 s, zero data loss |
| Mixed steady state | 1,000 concurrent users, 30 min | error rate < 0.1 %, no memory growth |

A regression beyond budget fails the nightly build. Load tests run against a database seeded to
the *next* growth stage, not the current one — finding the wall before users do is the entire
point.

---

## 9. Test data

- **Factories, not fixtures.** `polyfactory` builders with sensible defaults and explicit
  overrides for the field under test — so a test reads as "a user whose protein is low", not as
  40 lines of setup.
- **Realistic seed data:** 50 synthetic users with 6 months of plausible training and nutrition
  history, used for AI evaluation, chart development and performance testing. Generated, never
  copied from production.
- **No shared mutable state.** Every test creates what it needs and rolls back.
- **Deterministic:** seeded randomness, injected clock, frozen time where dates matter.

---

## 10. Quality gates

| Gate | Blocks |
|---|---|
| Lint + format (`ruff`, `eslint`, `prettier`) | merge |
| Types (`mypy --strict` on domain/application, `tsc --noEmit`) | merge |
| Architecture contracts (`import-linter`) | merge |
| Unit + integration + API tests | merge |
| Coverage ≥ 80 %, no decrease | merge |
| IDOR suite | merge |
| Security scans (SAST, SCA, secrets, container) | merge |
| OpenAPI breaking-change check | merge |
| Generated types up to date | merge |
| a11y (axe) | merge |
| AI safety evals | **deploy** |
| E2E | deploy |
| Performance budgets | nightly → ticket |

---

## 11. What we deliberately do not test

Stated explicitly so nobody adds them "for completeness":

- **Framework behaviour.** FastAPI routing and SQLAlchemy relationship loading are their
  maintainers' responsibility.
- **Third-party APIs.** Azure OpenAI and Open Food Facts are stubbed. We test *our* handling of
  their failures, not their uptime.
- **Trivial getters, DTO mappings, generated code.**
- **Exact copy strings.** Testing that a heading reads "Dashboard" makes copy changes expensive
  and catches nothing.
- **Implementation details.** Tests assert behaviour through public interfaces; a refactor that
  preserves behaviour should not turn the suite red. A suite that breaks on every refactor stops
  being a safety net and becomes a tax.

---

**Next:** [14 · Scalability & Operations](14-scalability-and-operations.md)
