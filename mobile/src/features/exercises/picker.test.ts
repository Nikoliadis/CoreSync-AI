import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The exercise picker, and the guarantee that matters most.
 *
 * A fabricated exercise id is the worst available bug here. It is accepted locally, the
 * user logs an entire workout against it, the queue flushes, and the server rejects
 * `exercise.add` because no such exercise exists — taking every set logged under it. The
 * failure surfaces long after the gym, with no obvious cause.
 *
 * So the central assertion is negative: nothing in this path mints an id. Every id comes
 * from the catalogue the server owns.
 */

const cache = vi.hoisted(() => ({
  cacheExercises: vi.fn(),
  searchCached: vi.fn(),
  cachedCount: vi.fn(),
}));

const client = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    code: string;
    details: unknown[] = [];
    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
    get isOffline() {
      return this.status === 0;
    }
  }
  return { api: { get: vi.fn() }, ApiError };
});

vi.mock("./cache", () => cache);
vi.mock("@/lib/api/client", () => client);

const { exercisesApi, primaryMuscle, equipmentLabel } = await import("./api");
const { usePickedExercise } = await import("./picked-exercise");

/** A real row, shaped exactly as `/v1/exercises` returns it. */
function exercise(overrides: Record<string, unknown> = {}) {
  return {
    id: "01925f3a-1c2d-7abc-8def-0123456789ab",
    slug: "barbell-bench-press",
    name: "Barbell Bench Press",
    categorySlug: "compound",
    loggingType: "weight_reps",
    difficulty: "intermediate" as const,
    forceType: "push",
    mechanic: "compound",
    isUnilateral: false,
    isVerified: true,
    isCustom: false,
    isFavorite: false,
    muscles: [
      {
        id: "m1",
        slug: "mid_chest",
        name: "Mid Chest",
        groupSlug: "chest",
        role: "primary",
        contributionPct: 60,
      },
      {
        id: "m2",
        slug: "triceps",
        name: "Triceps",
        groupSlug: "arms",
        role: "secondary",
        contributionPct: 20,
      },
    ],
    equipment: ["barbell", "flat_bench"],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  usePickedExercise.setState({ picked: null });
});

describe("querying the catalogue", () => {
  it("asks the real endpoint", async () => {
    client.api.get.mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0, hasMore: false });
    await exercisesApi.search({});

    expect(client.api.get).toHaveBeenCalledWith("/v1/exercises", expect.anything());
  });

  it("passes only filters the backend declares", async () => {
    // Inventing a query parameter is how a filter silently does nothing: FastAPI
    // ignores what it does not declare, so the UI would show a selected chip over
    // unfiltered results.
    client.api.get.mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0, hasMore: false });
    await exercisesApi.search({
      q: "bench",
      muscleGroup: "chest",
      equipment: "barbell",
      difficulty: "intermediate",
      favoritesOnly: true,
    });

    const { query } = client.api.get.mock.calls[0]?.[1] as { query: Record<string, unknown> };
    const SUPPORTED = new Set([
      "q",
      "muscle_group",
      "muscle",
      "equipment",
      "category",
      "difficulty",
      "logging_type",
      "favoritesOnly",
      "customOnly",
      "limit",
      "offset",
    ]);
    for (const key of Object.keys(query)) {
      expect(SUPPORTED.has(key), `${key} is not a parameter the API declares`).toBe(true);
    }
  });

  it("pages rather than pulling the whole catalogue", async () => {
    client.api.get.mockResolvedValue({ items: [], total: 274, limit: 30, offset: 0, hasMore: true });
    await exercisesApi.search({}, 60);

    const { query } = client.api.get.mock.calls[0]?.[1] as { query: Record<string, unknown> };
    expect(query.limit).toBe(30);
    expect(query.offset).toBe(60);
  });
});

describe("the row summary", () => {
  it("shows the primary mover, not whichever muscle came first", () => {
    expect(primaryMuscle(exercise())).toBe("Mid Chest");
  });

  it("falls back to the first muscle when no role is marked", () => {
    const unroled = exercise({
      muscles: [{ id: "m", slug: "s", name: "Quads", groupSlug: "legs", role: null, contributionPct: null }],
    });
    expect(primaryMuscle(unroled)).toBe("Quads");
  });

  it("is null when the exercise lists no muscles", () => {
    expect(primaryMuscle(exercise({ muscles: [] }))).toBeNull();
  });

  it("renders equipment slugs as words", () => {
    // `flat_bench` read as-is looks like a database row rather than a piece of kit.
    expect(equipmentLabel(exercise())).toBe("barbell, flat bench");
  });

  it("is null for a bodyweight exercise", () => {
    expect(equipmentLabel(exercise({ equipment: [] }))).toBeNull();
  });
});

describe("handing the choice back", () => {
  it("carries the catalogue id unchanged", () => {
    const chosen = exercise();
    usePickedExercise.getState().pick({ id: chosen.id, name: chosen.name });

    expect(usePickedExercise.getState().picked?.id).toBe(chosen.id);
  });

  it("clears as it is read, so a pick cannot be applied twice", () => {
    // The workout screen consumes this on focus. Without clearing, navigating back for
    // any other reason would add the same exercise again.
    usePickedExercise.getState().pick({ id: "abc", name: "Squat" });

    expect(usePickedExercise.getState().consume()?.id).toBe("abc");
    expect(usePickedExercise.getState().consume()).toBeNull();
    expect(usePickedExercise.getState().picked).toBeNull();
  });

  it("returns null when nothing was picked", () => {
    expect(usePickedExercise.getState().consume()).toBeNull();
  });
});

describe("no id is ever fabricated", () => {
  it("the picker module never imports a uuid generator", async () => {
    // The guarantee, enforced structurally rather than by inspection. An id minted here
    // is accepted locally and rejected by the server on sync, losing every set logged
    // against it — so the safest version of this module is one that *cannot* mint one.
    const fs = await import("node:fs/promises");
    const sources = await Promise.all(
      [
        "src/features/exercises/api.ts",
        "src/features/exercises/cache.ts",
        "src/features/exercises/picked-exercise.ts",
        "src/features/exercises/use-exercise-search.ts",
        "app/workout/exercise-picker.tsx",
      ].map((path) => fs.readFile(path, "utf8")),
    );

    for (const source of sources) {
      expect(source).not.toMatch(/uuid7|randomUUID|uuidv4/);
    }
  });

  it("the active workout no longer contains a hardcoded exercise id", async () => {
    const fs = await import("node:fs/promises");
    const source = await fs.readFile("app/workout/active.tsx", "utf8");

    // The placeholder this task replaced. Any bare UUID literal in that file would be a
    // production id hardcoded into a client, which is its own problem.
    expect(source).not.toMatch(/["'][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}["']/i);
  });
});
