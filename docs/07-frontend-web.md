# 07 · Web Frontend

Next.js 15 (App Router) · React 19 · TypeScript (strict) · TailwindCSS · TanStack Query ·
Zustand · Framer Motion. Deployed on Vercel.

---

## 1. Rendering strategy

The wrong instinct with the App Router is to make everything a Server Component. This app has
two halves with opposite needs.

| Surface | Rendering | Why |
|---|---|---|
| Marketing, pricing, blog, legal | **Static (SSG)** + ISR | SEO and speed. No user data involved |
| Auth pages | Server Component shell, client form | Fast paint, no data to fetch |
| Dashboard, workouts, diary, progress | **Client Components** over TanStack Query | Highly interactive, per-user, offline-tolerant, and shares its entire data layer with the mobile app |
| Public profile / shared workout | **SSR** | Shareable links need OG tags and crawlable content |
| Admin panel | Client Components | Internal tool; SEO irrelevant, interactivity high |

**Why the authenticated app is client-rendered.** Server Components would mean the Next.js
server holds the user's session and proxies every API call — doubling the network hops, making
optimistic updates awkward, and forcing a second implementation of a data layer that mobile
already needs in the client. One TanStack Query layer shared conceptually between web and mobile
is worth more than a marginally faster first paint on a screen users reach while already logged
in. The app shell is prefetched and cached; perceived load is dominated by the API, not by React.

---

## 2. Folder structure

```text
apps/web/
├── app/
│   ├── (marketing)/                  # static, public
│   │   ├── page.tsx                  # landing
│   │   ├── pricing/  features/  blog/
│   │   └── layout.tsx
│   ├── (auth)/
│   │   ├── login/  register/  verify/  reset-password/
│   │   └── layout.tsx                # centred card layout
│   ├── (app)/                        # authenticated shell
│   │   ├── layout.tsx                # sidebar + topbar + providers + auth guard
│   │   ├── dashboard/page.tsx
│   │   ├── workouts/
│   │   │   ├── page.tsx              # history
│   │   │   ├── active/page.tsx       # live session logger
│   │   │   ├── routines/[id]/edit/page.tsx
│   │   │   └── [sessionId]/page.tsx
│   │   ├── nutrition/
│   │   │   ├── page.tsx              # diary (date-driven)
│   │   │   ├── foods/[id]/page.tsx
│   │   │   └── recipes/
│   │   ├── progress/
│   │   │   ├── page.tsx  weight/  measurements/  photos/
│   │   ├── coach/
│   │   │   ├── page.tsx              # AI chat
│   │   │   └── reports/[id]/page.tsx
│   │   ├── social/  settings/
│   ├── (admin)/admin/…               # role-guarded
│   ├── u/[username]/page.tsx         # SSR public profile
│   ├── api/                          # BFF-only: OAuth callbacks, webhooks, OG images
│   ├── layout.tsx                    # html, fonts, theme script
│   ├── globals.css
│   └── error.tsx  not-found.tsx
│
├── src/
│   ├── features/                     # ← the app is organised by feature, not by file type
│   │   ├── workouts/
│   │   │   ├── api/                  # queries.ts, mutations.ts, keys.ts
│   │   │   ├── components/           # SetRow, RestTimer, ExercisePicker, VolumeChart
│   │   │   ├── hooks/                # useActiveSession, useRestTimer
│   │   │   ├── stores/               # activeSessionStore (Zustand)
│   │   │   ├── utils/                # formatSet, oneRepMax
│   │   │   └── types.ts
│   │   ├── nutrition/  progress/  coach/  auth/  social/  settings/
│   │
│   ├── components/
│   │   ├── ui/                       # design-system primitives (Button, Card, Sheet…)
│   │   ├── charts/                   # Recharts wrappers with the shared theme
│   │   ├── layout/                   # Sidebar, TopBar, MobileNav
│   │   └── providers/                # QueryProvider, ThemeProvider, ToastProvider
│   │
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts             # fetch wrapper: auth, refresh, errors, tracing
│   │   │   ├── query-client.ts
│   │   │   └── generated/            # ← openapi-typescript output, never hand-edited
│   │   ├── auth/                     # token store, session hooks, route guards
│   │   ├── units/                    # kg↔lb, cm↔in, ml↔fl-oz
│   │   ├── dates/                    # user-timezone-aware date helpers
│   │   └── utils/                    # cn(), formatters
│   │
│   ├── stores/                       # cross-feature client state only
│   │   ├── ui-store.ts               # sidebar, modals, active date
│   │   └── preferences-store.ts      # units, theme (persisted)
│   └── styles/
├── public/
├── tailwind.config.ts
└── next.config.ts
```

**Feature-first, not type-first.** `features/workouts/` holds everything about workouts. A
developer changing set logging touches one directory. The alternative — `components/`, `hooks/`,
`api/` at the top level — spreads every change across four places and scales badly past ~20
screens.

---

## 3. Data layer

### 3.1 Server state vs client state

The single most important rule: **TanStack Query owns everything that comes from the server;
Zustand owns only what never does.**

| Owner | Examples |
|---|---|
| **TanStack Query** | User, workouts, routines, diary, foods, weight, photos, insights — everything with an id |
| **Zustand** | Active-session draft before sync, rest-timer state, selected date, sidebar open, unit preference, theme |

Putting server data in Zustand recreates caching, invalidation, retries, dedupe and stale
handling by hand — badly. This is the most common architectural mistake in React apps of this
size.

### 3.2 Query keys

```ts
// features/workouts/api/keys.ts
export const workoutKeys = {
  all:        ['workouts'] as const,
  sessions:   () => [...workoutKeys.all, 'sessions'] as const,
  session:    (id: string) => [...workoutKeys.sessions(), id] as const,
  history:    (filters: HistoryFilters) => [...workoutKeys.sessions(), 'history', filters] as const,
  active:     () => [...workoutKeys.sessions(), 'active'] as const,
  routines:   () => [...workoutKeys.all, 'routines'] as const,
  routine:    (id: string) => [...workoutKeys.routines(), id] as const,
  calendar:   (from: string, to: string) => [...workoutKeys.all, 'calendar', from, to] as const,
};
```

Hierarchical keys make invalidation precise: `invalidateQueries({ queryKey: workoutKeys.sessions() })`
clears every session query and nothing else.

### 3.3 Optimistic set logging

The interaction the whole product is judged on. It must feel instant.

```ts
// features/workouts/api/mutations.ts
export function useLogSet(sessionId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (input: LogSetInput) => api.workouts.logSet(sessionId, input),

    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: workoutKeys.session(sessionId) });
      const previous = qc.getQueryData<WorkoutSession>(workoutKeys.session(sessionId));

      // The id is generated on the client (UUIDv7) — the same id the server will persist,
      // so reconciliation is an identity match, not a guess.
      qc.setQueryData<WorkoutSession>(workoutKeys.session(sessionId), (old) =>
        old ? addSetToSession(old, { ...input, id: input.id, pending: true }) : old,
      );
      return { previous };
    },

    onError: (_err, _input, ctx) => {
      if (ctx?.previous) qc.setQueryData(workoutKeys.session(sessionId), ctx.previous);
      toast.error('Set not saved — retrying');
    },

    onSuccess: (serverSet) => {
      qc.setQueryData<WorkoutSession>(workoutKeys.session(sessionId), (old) =>
        old ? replaceSet(old, serverSet) : old,
      );
    },

    // Deliberately not invalidating the session query here: a refetch mid-workout would
    // stall the UI on a slow gym connection. The optimistic state is already correct.
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  });
}
```

### 3.4 Query client defaults

```ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,              // fitness data does not change second to second
      gcTime: 15 * 60_000,
      retry: (failureCount, error) =>
        isNetworkError(error) && failureCount < 3,   // never retry a 4xx
      refetchOnWindowFocus: false,     // refetching a diary on every tab switch is jarring
      refetchOnReconnect: true,
    },
    mutations: { retry: 1 },
  },
});
```

Per-resource overrides: reference data (`exercises`, muscle groups) gets `staleTime: Infinity`;
the active session gets `staleTime: 0`.

### 3.5 API client

```ts
// lib/api/client.ts — single-flight refresh, typed errors, tracing
let refreshPromise: Promise<void> | null = null;

async function request<T>(path: string, init: RequestInit & { retry?: boolean } = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',                     // refresh cookie
    headers: {
      'Content-Type': 'application/json',
      'X-Request-Id': crypto.randomUUID(),
      'X-Client-Version': CLIENT_VERSION,
      'X-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone,
      ...(tokenStore.access && { Authorization: `Bearer ${tokenStore.access}` }),
      ...init.headers,
    },
  });

  if (res.status === 401 && !init.retry) {
    refreshPromise ??= refreshAccessToken().finally(() => { refreshPromise = null; });
    await refreshPromise;                       // every queued 401 waits on one refresh
    return request<T>(path, { ...init, retry: true });
  }
  if (!res.ok) throw await ApiError.fromResponse(res);
  return res.status === 204 ? (undefined as T) : res.json();
}
```

Types come from `lib/api/generated/`, produced from the backend's OpenAPI spec in CI
([04](04-api-design.md) §8). No hand-written request or response interfaces exist in the web app.

---

## 4. State management with Zustand

```ts
// features/workouts/stores/active-session-store.ts
interface ActiveSessionState {
  sessionId: string | null;
  startedAt: number | null;
  restTimer: { exerciseId: string; endsAt: number } | null;
  draftSets: Record<string, DraftSet>;     // keyed by client-generated set id
  startSession: (id: string) => void;
  startRest: (exerciseId: string, seconds: number) => void;
  clearRest: () => void;
  reset: () => void;
}

export const useActiveSessionStore = create<ActiveSessionState>()(
  persist(
    (set) => ({
      sessionId: null, startedAt: null, restTimer: null, draftSets: {},
      startSession: (id) => set({ sessionId: id, startedAt: Date.now(), draftSets: {} }),
      startRest: (exerciseId, seconds) =>
        set({ restTimer: { exerciseId, endsAt: Date.now() + seconds * 1000 } }),
      clearRest: () => set({ restTimer: null }),
      reset: () => set({ sessionId: null, startedAt: null, restTimer: null, draftSets: {} }),
    }),
    { name: 'gympulse:active-session', partialize: (s) => ({ ...s, restTimer: s.restTimer }) },
  ),
);
```

**The rest timer stores an absolute `endsAt`, not a countdown.** A countdown decremented by
`setInterval` drifts, and stops entirely when the tab is backgrounded — which is exactly when
the user is resting. Storing the end timestamp and deriving the remaining time on each render is
correct across tab suspension, page reloads and clock changes.

**Selectors, always** — `useActiveSessionStore((s) => s.restTimer)`, never the whole store. The
latter re-renders every consumer on any change.

---

## 5. Forms & validation

React Hook Form + Zod. **Zod schemas are derived from the generated OpenAPI types**, so client
validation cannot drift from server validation.

```ts
const logSetSchema = z.object({
  reps: z.number().int().min(0).max(1000),
  weightKg: z.number().min(0).max(1000).multipleOf(0.25),
  rpe: z.number().min(1).max(10).optional(),
  setType: z.enum(['normal', 'warmup', 'drop', 'failure', 'amrap']).default('normal'),
});
```

Server validation remains authoritative — client validation exists for UX, never for security.
The set-logging form is the exception to normal form patterns: it submits on change with a
debounce rather than on an explicit submit, because a lifter should never press "Save".

---

## 6. Charts

Recharts, wrapped once in `components/charts/` so every chart shares theme, tooltip, axis and
empty-state behaviour. Rules:

- **Weight charts plot the smoothed trend as the primary line** and raw weigh-ins as faint dots.
  Raw daily weight is mostly water and glycogen noise; showing it as the headline makes users
  panic at a 1.5 kg overnight "gain".
- Colour is never the only encoding — shape and label carry the same information (accessibility).
- Charts are lazy-loaded (`next/dynamic`, `ssr: false`): Recharts is large, and the dashboard's
  first paint should not wait for it.
- Every chart declares an explicit empty state. A new user sees "Log your first weigh-in", not
  an empty grid.

---

## 7. Performance

| Technique | Application |
|---|---|
| Route-level code splitting | Automatic per route group; charts, editors and the admin bundle are dynamically imported |
| `next/image` | All exercise media and photos; AVIF/WebP, explicit sizes, blur placeholders |
| `next/font` | Self-hosted variable font, `display: swap`, preloaded — zero layout shift, no third-party request |
| Virtualisation | `@tanstack/react-virtual` for exercise lists (600+), food search results and long histories |
| Prefetch | `<Link prefetch>` on primary nav; `queryClient.prefetchQuery` on hover for session details |
| Debounce | Food search 300 ms; set inputs 500 ms |
| Bundle budget | 180 KB gzipped for the initial authenticated route. CI fails on regression |

**Core Web Vitals targets:** LCP < 2.0 s, INP < 200 ms, CLS < 0.05 — measured on real users via
Vercel Analytics, not only in the lab.

---

## 8. Theming

```tsx
// Inlined in <head>, before hydration — prevents the white flash on a dark-mode reload.
<script dangerouslySetInnerHTML={{ __html: `
  (function () {
    try {
      var s = localStorage.getItem('gympulse:theme') || 'system';
      var d = s === 'dark' || (s === 'system' &&
              matchMedia('(prefers-color-scheme: dark)').matches);
      document.documentElement.classList.toggle('dark', d);
      document.documentElement.style.colorScheme = d ? 'dark' : 'light';
    } catch (e) {}
  })();
`}} />
```

Tokens are CSS custom properties consumed by Tailwind, so a theme change is a class on `<html>`
and nothing re-renders. Full token set in [09 · Design System](09-design-system.md).

---

## 9. Accessibility

Not a checklist item — a lot of this app is used one-handed, sweaty, on a phone propped against
a rack.

- Radix UI primitives underneath every interactive component: correct roles, focus traps,
  keyboard behaviour and screen-reader semantics by default.
- Touch targets ≥ 44 × 44 px on every logging control.
- Focus visible everywhere; a keyboard user can log an entire workout.
- Contrast ≥ 4.5:1 for text and ≥ 3:1 for UI boundaries, verified in both themes.
- `prefers-reduced-motion` disables every non-essential animation.
- Live regions announce PRs, rest-timer completion and save failures.
- `axe-core` runs in CI on every route; violations fail the build.

---

## 10. Error handling

| Level | Mechanism |
|---|---|
| Route | `error.tsx` per route group — a broken chart never blanks the app |
| Component | Error boundaries around charts, the AI chat stream and third-party embeds |
| Query | `useQuery` error states render inline retry affordances, not full-page errors |
| Mutation | Toast + automatic rollback of the optimistic update |
| Global | Sentry with source maps, `X-Request-Id` attached so a frontend error links to its backend trace |
| Offline | A banner appears on `navigator.onLine === false`; writes queue and flush on reconnect |

---

## 11. Testing

| Layer | Tool | Scope |
|---|---|---|
| Unit | Vitest | Utils, unit conversion, 1RM maths, date helpers |
| Component | Testing Library | Behaviour, not implementation. Queries by role/label |
| Integration | Vitest + MSW | Feature flows against a mocked API driven by the OpenAPI spec |
| E2E | Playwright | Register → onboard → log workout → log food → view progress, on Chromium + WebKit |
| Visual | Playwright screenshots | Design-system components in both themes |
| A11y | axe-core | Every route |

MSW handlers are generated from the same OpenAPI spec as the types, so the mocks cannot drift
from the real API.

---

**Next:** [08 · Mobile](08-mobile.md)
