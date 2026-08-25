import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The offline half of the picker.
 *
 * The cache is a read-through copy of a catalogue the server owns. Nothing is created
 * here and nothing is written back, so the only ways it can be wrong are: returning
 * something the filters exclude, or failing to return something it holds.
 *
 * The row shape is JSON in a blob, so a corrupt row is a real possibility — a partial
 * write, a schema change, a truncated payload. One bad row must not take the search
 * with it, because the alternative is a picker that shows nothing at all.
 */

const database = vi.hoisted(() => ({
  getAllAsync: vi.fn(),
  getFirstAsync: vi.fn(),
  runAsync: vi.fn(),
  withTransactionAsync: vi.fn(async (fn: () => Promise<void>) => fn()),
}));

vi.mock("@/offline/database", () => ({
  openDatabase: () => Promise.resolve(database),
}));

const { cacheExercises, searchCached, cachedCount } = await import("./cache");

function row(overrides: Record<string, unknown> = {}) {
  return {
    id: "01925f3a-1c2d-7abc-8def-0123456789ab",
    slug: "bench",
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
    muscles: [{ id: "m", slug: "mid_chest", name: "Mid Chest", groupSlug: "chest", role: "primary", contributionPct: 60 }],
    equipment: ["barbell"],
    ...overrides,
  };
}

function stored(...items: ReturnType<typeof row>[]) {
  return items.map((item, index) => ({
    id: item.id,
    payload: JSON.stringify(item),
    cached_at: 1_700_000_000_000 + index,
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  database.runAsync.mockResolvedValue(undefined);
});

describe("writing", () => {
  it("stores each exercise", async () => {
    await cacheExercises([row(), row({ id: "b", name: "Squat" })]);
    expect(database.runAsync).toHaveBeenCalledTimes(2);
  });

  it("does nothing for an empty page", async () => {
    await cacheExercises([]);
    expect(database.runAsync).not.toHaveBeenCalled();
    expect(database.withTransactionAsync).not.toHaveBeenCalled();
  });

  it("upserts rather than replacing the table", async () => {
    // Results arrive filtered and paginated. Wiping on every search would leave the
    // cache holding only the last thing looked at — the opposite of useful offline.
    await cacheExercises([row()]);
    const sql = database.runAsync.mock.calls[0]?.[0] as string;
    expect(sql).toMatch(/ON CONFLICT\(id\) DO UPDATE/i);
  });
});

describe("searching", () => {
  it("matches on name, case-insensitively", async () => {
    database.getAllAsync.mockResolvedValue(stored(row(), row({ id: "b", name: "Squat" })));
    const found = await searchCached({ q: "BENCH" }, 10);

    expect(found.map((item) => item.name)).toEqual(["Barbell Bench Press"]);
  });

  it("matches a substring, not just a prefix", async () => {
    database.getAllAsync.mockResolvedValue(stored(row()));
    expect(await searchCached({ q: "bench press" }, 10)).toHaveLength(1);
  });

  it("filters by difficulty", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(row(), row({ id: "b", name: "Push-up", difficulty: "beginner" })),
    );
    const found = await searchCached({ difficulty: "beginner" }, 10);
    expect(found.map((item) => item.name)).toEqual(["Push-up"]);
  });

  it("filters by equipment", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(row(), row({ id: "b", name: "Push-up", equipment: [] })),
    );
    const found = await searchCached({ equipment: "barbell" }, 10);
    expect(found.map((item) => item.name)).toEqual(["Barbell Bench Press"]);
  });

  it("filters by muscle group", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(
        row(),
        row({
          id: "b",
          name: "Squat",
          muscles: [{ id: "m", slug: "quads", name: "Quads", groupSlug: "legs", role: "primary", contributionPct: 60 }],
        }),
      ),
    );
    const found = await searchCached({ muscleGroup: "legs" }, 10);
    expect(found.map((item) => item.name)).toEqual(["Squat"]);
  });

  it("filters by favourite", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(row(), row({ id: "b", name: "Squat", isFavorite: true })),
    );
    const found = await searchCached({ favoritesOnly: true }, 10);
    expect(found.map((item) => item.name)).toEqual(["Squat"]);
  });

  it("combines filters", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(
        row(),
        row({ id: "b", name: "Bench Press Dumbbell", equipment: ["dumbbell"] }),
      ),
    );
    const found = await searchCached({ q: "bench", equipment: "dumbbell" }, 10);
    expect(found.map((item) => item.name)).toEqual(["Bench Press Dumbbell"]);
  });

  it("respects the limit", async () => {
    database.getAllAsync.mockResolvedValue(
      stored(...Array.from({ length: 20 }, (_, i) => row({ id: `x${i}`, name: `Row ${i}` }))),
    );
    expect(await searchCached({}, 5)).toHaveLength(5);
  });

  it("sorts alphabetically", async () => {
    // Not by relevance — the cache cannot reproduce the server's ranking, and a stable
    // predictable order is more honest than pretending to.
    database.getAllAsync.mockResolvedValue(
      stored(row({ id: "c", name: "Squat" }), row({ id: "a", name: "Bench" })),
    );
    const found = await searchCached({}, 10);
    expect(found.map((item) => item.name)).toEqual(["Bench", "Squat"]);
  });

  it("returns nothing when the cache is empty", async () => {
    database.getAllAsync.mockResolvedValue([]);
    expect(await searchCached({ q: "anything" }, 10)).toEqual([]);
  });

  it("skips a corrupt row instead of failing the search", async () => {
    // A truncated write or a schema change leaves unparseable JSON. Throwing here would
    // turn one bad row into an empty picker.
    database.getAllAsync.mockResolvedValue([
      { id: "bad", payload: "{not json", cached_at: 1 },
      ...stored(row()),
    ]);
    const found = await searchCached({}, 10);
    expect(found.map((item) => item.name)).toEqual(["Barbell Bench Press"]);
  });

  it("returns ids exactly as stored", async () => {
    // The whole point. The id that comes out of the cache is the catalogue id that went
    // in, unmodified — anything else and the workout syncs against an exercise the
    // server has never heard of.
    database.getAllAsync.mockResolvedValue(stored(row()));
    const found = await searchCached({}, 10);
    expect(found[0]?.id).toBe("01925f3a-1c2d-7abc-8def-0123456789ab");
  });
});

describe("counting", () => {
  it("reports how much is cached", async () => {
    database.getFirstAsync.mockResolvedValue({ count: 42 });
    expect(await cachedCount()).toBe(42);
  });

  it("reports zero when the table is empty", async () => {
    database.getFirstAsync.mockResolvedValue(null);
    expect(await cachedCount()).toBe(0);
  });
});
