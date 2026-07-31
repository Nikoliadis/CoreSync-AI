# 16 · Phase 6 hardening — status

What is built, what is verified, and what is honestly still open. Companion to
[15 · Roadmap](15-roadmap.md) §Phase 6.

Written because "hardening" is the phase where a checklist quietly becomes a claim.
Everything below is either marked as verified by a named test, or marked as not done.

---

## 1. Notifications

**Built and verified.**

| Piece | State |
|---|---|
| Categories, per-category opt-out | Done. `SYSTEM` is unsilenceable — account and security messages are not a preference |
| Quiet hours, timezone-aware | Done. Local wall-clock hours, so the window survives travel and DST |
| Deferral rather than dropping | Done. A 23:30 PR is delivered at 07:00, not discarded |
| Outbox dispatcher | Done. `SELECT … FOR UPDATE SKIP LOCKED`, three attempts, then `failed` |
| Channel selection | Done. Push only when a device token exists; email reserved for weekly reports and system notices |
| Deep links | Stored per notification as an app route, resolved by each platform |
| In-app list, unread count, mark-read | Done, idempotent at the SQL level |

Tested by `tests/unit/domain/test_notifications.py` (39 cases — the midnight-wrapping
window is the one a naive range check gets wrong for every hour of the night) and
`tests/api/test_notifications_and_admin.py`.

**Not done:** no real push provider is wired (APNs/FCM), and no scheduled job invokes
the dispatcher. `DispatchOutboxUseCase` is complete and tested against a fake sender;
what is missing is the Celery beat entry and the provider credentials. Nothing sends
yet, and the UI says so.

---

## 2. Admin panel

**Built and verified, deliberately read-only.**

Role guard is declared on the router, not per endpoint — a guard added route by route
is one that gets forgotten on the next route, and the failure is silent. Every admin
route is exercised by an ordinary user and by an anonymous caller in
`TestAdminAccessControl`; both are refused, and the 403 body is asserted to leak
nothing about what the endpoint would have returned.

The user list exposes id, email, role, status and creation date, and the test asserts
that set exactly — support does not need training, body or conversation data, and a
panel that shows them is a breach waiting for a bored employee. AI figures are
aggregates; there is no code path that returns a transcript.

**Not done:** exercise and food moderation, announcements, feature flags. Mutations
need an audit trail of who changed what before they need the feature.

---

## 3. Accessibility

**Gate built, running, and it found three real bugs.**

`frontend/e2e/accessibility.spec.ts` runs axe-core against every public route in
**both themes**, plus keyboard reachability and a focus-ring assertion. Wired into
`.github/workflows/web-ci.yml`. Playwright rather than `@axe-core/cli` because the
latter pairs system Chrome with a separately versioned chromedriver and breaks when
they drift — which it did, locally, immediately.

What it caught, all of which shipped broken before it existed:

1. **Every primary button rendered white-on-lime at 1.17:1.** `tailwind-merge` does
   not know the project's type scale, so it treated `text-accent-ink` (a colour) and
   `text-body` (a size) as the same `text-*` group and dropped the colour. Fixed by
   teaching `cn()` the scale; the CSS had been correct all along, the class never
   reached the DOM.
2. **Accent text was unreadable in light mode**, at 1.07:1 on the page surface. The
   brand lime is a *fill* colour; there was no text-safe variant. Added
   `--color-accent-text`, which stays bright in dark (16.8:1) and darkens to `#4f660d`
   in light (worst case 5.68:1 across all four light surfaces).
3. **The focus ring was suppressed app-wide.** `outline-none` sits in Tailwind's
   utilities layer and beat the base-layer `:focus-visible` rule, so buttons, the
   chat composer and every set-row input had no visible focus indicator at all.

**Not done:** the authenticated shell is not covered — those routes need a seeded
session. Manual VoiceOver and TalkBack passes have not been run, and cannot be
automated away.

---

## 4. Security

**Reviewed, partially verified. No external pen test has been performed.**

Verified by tests:

- Cross-user access is refused on conversations, insights and notifications
  (`test_another_users_conversation_is_not_reachable`, and ownership is a predicate in
  every repository query rather than a check afterwards).
- Admin routes refuse ordinary and anonymous callers.
- The password-reset endpoint answers identically for known and unknown addresses, so
  it is not an account-enumeration oracle.
- OAuth sign-in refuses an unverified provider email outright.
- Rate limiting fails **open** (availability over enforcement); token revocation fails
  **closed** with a 503 (security over availability). That asymmetry is deliberate.
- The AI output guard withholds the tail of a streamed reply so an unsafe fragment is
  never emitted, verified at both unit and API level.

Known and unresolved:

- **12 high-severity npm advisories**, all upstream: Next 16's pinned `sharp`/libvips
  and ESLint's `minimatch` chain. No non-breaking fix exists; forcing one downgrades
  Next. Re-check on the next Next release.
- **Migrations 0001 and 0002 contain doubled constraint names**
  (`ck_exercises_ck_exercises_force_type_valid`), truncated to hashes past 63
  characters. Cosmetic, but it makes a constraint violation harder to read in a log.
  0003 onward are correct.
- **No external pen test.** This is a roadmap exit criterion and cannot be satisfied
  from inside the codebase.

---

## 5. Not started

Named here rather than omitted, because a phase status that lists only what was done
is a status report that lies by construction.

| Deliverable | Why not |
|---|---|
| Achievements | Definitions and the awarding job. The records exist; the rules do not |
| Performance / load testing | Needs a staging environment at stage-2 volumes |
| i18n (EN + EL) | No strings are externalised yet |
| Store submission | Needs the mobile app, which is Phase 8 |
| Closed beta | Needs 200–500 real users over three weeks |
| External pen test | Needs a third party |

---

## 6. Exit criteria

From [15 · Roadmap](15-roadmap.md): *pen test clean · crash-free sessions > 99.5 % ·
beta D7 retention > 30 % · store builds approved · all [11](11-security.md) §12
checklist items ticked.*

**None of these are met**, and none of them can be met from the codebase alone — every
one needs either a third party, a staging environment, or real users. Phase 6 is
partially delivered: the engineering that could be built and verified has been; the
validation that requires the outside world has not.
