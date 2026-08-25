import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Nutrition: the API contract, dates, and the cache.
 *
 * The date tests carry more weight than they look. A diary day is the *user's* local
 * day, and `toISOString()` at 01:00 in Athens returns yesterday — which files breakfast
 * under the wrong date and quietly breaks the streak that depends on it. The backend
 * stores `local_date` in the user's timezone for exactly this reason; the client has to
 * agree with it.
 */

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
  return {
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
    ApiError,
  };
});

const database = vi.hoisted(() => ({
  getFirstAsync: vi.fn(),
  runAsync: vi.fn(),
}));

vi.mock("@/lib/api/client", () => client);
vi.mock("@/offline/database", () => ({ openDatabase: () => Promise.resolve(database) }));

const { nutritionApi, kcal, grams, portion, MEAL_ORDER } = await import("./api");
const { localToday, shiftDate, friendlyDate, isFuture, toLocalISO } = await import("./dates");
const { cacheDiary, cachedDiary } = await import("./cache");

function diary(overrides: Record<string, unknown> = {}) {
  return {
    localDate: "2026-08-25",
    totals: {
      calories: "1850.00",
      proteinG: "142.00",
      carbsG: "180.00",
      fatG: "60.00",
      alcoholG: "0.00",
    },
    waterMl: "1500.000",
    byMeal: [],
    entries: [],
    targets: null,
    remaining: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  database.runAsync.mockResolvedValue(undefined);
});

describe("the API contract", () => {
  it("reads a specific day", async () => {
    client.api.get.mockResolvedValue(diary());
    await nutritionApi.diary("2026-08-24");

    expect(client.api.get).toHaveBeenCalledWith("/v1/nutrition/diary", {
      query: { on: "2026-08-24" },
    });
  });

  it("logs a food against a meal and a date", async () => {
    client.api.post.mockResolvedValue({});
    await nutritionApi.logFood({
      foodId: "food-1",
      mealType: "lunch",
      quantity: 150,
      servingId: null,
      localDate: "2026-08-25",
    });

    const [path, body] = client.api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/v1/nutrition/diary");
    expect(body.mealType).toBe("lunch");
    expect(body.quantity).toBe(150);
    expect(body.localDate).toBe("2026-08-25");
  });

  it("sends only the fields being changed on an edit", async () => {
    // PATCH semantics: an omitted field means "leave it alone", so sending the whole
    // entry back would overwrite anything changed elsewhere in between.
    client.api.patch.mockResolvedValue({});
    await nutritionApi.editEntry("entry-1", { quantity: 200 });

    const [path, body] = client.api.patch.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/v1/nutrition/diary/entry-1");
    expect(Object.keys(body)).toEqual(["quantity"]);
  });

  it("copies a whole day when no meal is named", async () => {
    client.api.post.mockResolvedValue({ copied: 4, targetDate: "2026-08-25" });
    await nutritionApi.copyDay({ sourceDate: "2026-08-24", targetDate: "2026-08-25" });

    const [, body] = client.api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.mealType).toBeUndefined();
  });

  it("logs water against the day it belongs to", async () => {
    // Not the server's day. A glass at 01:00 in Athens belongs to the Athens date.
    client.api.post.mockResolvedValue({ localDate: "2026-08-25", totalMl: "250" });
    await nutritionApi.logWater(250, "2026-08-25");

    const [, body] = client.api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.localDate).toBe("2026-08-25");
  });

  it("unwraps the history envelope", async () => {
    client.api.get.mockResolvedValue({ items: [{ localDate: "2026-08-24" }] });
    const items = await nutritionApi.history(7);

    expect(Array.isArray(items)).toBe(true);
    expect(items[0]?.localDate).toBe("2026-08-24");
  });
});

describe("diary dates", () => {
  it("returns an ISO date, not a timestamp", () => {
    expect(localToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("agrees with the device's own idea of today", () => {
    // The bug this guards: `toISOString()` at 01:00 in Athens returns yesterday, so
    // breakfast is filed under the wrong day and the streak silently breaks.
    const now = new Date();
    const expected = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("-");
    expect(localToday()).toBe(expected);
  });

  it("steps across a month boundary", () => {
    expect(shiftDate("2026-09-01", -1)).toBe("2026-08-31");
  });

  it("steps across a year boundary", () => {
    expect(shiftDate("2027-01-01", -1)).toBe("2026-12-31");
  });

  it("handles a leap day", () => {
    expect(shiftDate("2028-02-28", 1)).toBe("2028-02-29");
  });

  it("survives a daylight-saving transition", () => {
    // The EU shifts on the last Sunday of March. Parsing at local midnight and
    // re-normalising is what stops this landing on the 28th.
    expect(shiftDate("2026-03-28", 1)).toBe("2026-03-29");
    expect(shiftDate("2026-10-24", 1)).toBe("2026-10-25");
  });

  it("round-trips", () => {
    expect(shiftDate(shiftDate("2026-08-25", -7), 7)).toBe("2026-08-25");
  });

  it("names today and yesterday", () => {
    expect(friendlyDate(localToday())).toBe("Today");
    expect(friendlyDate(shiftDate(localToday(), -1))).toBe("Yesterday");
  });

  it("knows tomorrow is in the future", () => {
    expect(isFuture(shiftDate(localToday(), 1))).toBe(true);
    expect(isFuture(localToday())).toBe(false);
  });

  it("converts a Date without drifting into the previous day", () => {
    const justAfterMidnight = new Date(2026, 7, 25, 0, 30);
    expect(toLocalISO(justAfterMidnight)).toBe("2026-08-25");
  });
});

describe("display helpers", () => {
  it("rounds calories", () => {
    expect(kcal("330.40")).toBe(330);
    expect(kcal("330.60")).toBe(331);
  });

  it("treats a missing value as zero rather than NaN", () => {
    expect(kcal(null)).toBe(0);
    expect(grams(undefined)).toBe(0);
  });

  it("drops a meaningless decimal but keeps one that says something", () => {
    expect(portion("116.000")).toBe("116");
    expect(portion("0.500")).toBe("0.5");
  });

  it("orders meals the way a day happens", () => {
    expect(MEAL_ORDER).toEqual(["breakfast", "lunch", "dinner", "snack"]);
  });
});

describe("the diary cache", () => {
  it("stores a day keyed by its date", async () => {
    await cacheDiary(diary());

    const [sql, id, localDate] = database.runAsync.mock.calls[0] as [string, string, string];
    expect(sql).toMatch(/ON CONFLICT\(id\) DO UPDATE/i);
    expect(id).toBe("diary:2026-08-25");
    expect(localDate).toBe("2026-08-25");
  });

  it("reads a cached day back intact", async () => {
    database.getFirstAsync.mockResolvedValue({
      id: "diary:2026-08-25",
      local_date: "2026-08-25",
      payload: JSON.stringify(diary()),
      updated_at: 1,
    });

    const found = await cachedDiary("2026-08-25");
    expect(found?.totals.calories).toBe("1850.00");
  });

  it("is a miss when the day was never cached", async () => {
    database.getFirstAsync.mockResolvedValue(null);
    expect(await cachedDiary("2026-01-01")).toBeNull();
  });

  it("treats a corrupt row as a miss rather than throwing", async () => {
    // A truncated write or a schema change leaves unparseable JSON. Throwing would take
    // the whole screen down over a disposable cache.
    database.getFirstAsync.mockResolvedValue({
      id: "diary:2026-08-25",
      local_date: "2026-08-25",
      payload: "{not json",
      updated_at: 1,
    });
    expect(await cachedDiary("2026-08-25")).toBeNull();
  });
});

describe("nutrition writes are never queued", () => {
  it("has no enqueue path, unlike the workout mutations", async () => {
    // The reason, stated as a test. `POST /v1/nutrition/diary` takes no client id — the
    // server mints the entry — and there is no nutrition sync endpoint. A queued write
    // replayed after a failed flush would create a second entry rather than reconcile
    // with the first, so somebody's dinner would appear twice.
    //
    // Workouts can queue precisely because they carry client-minted ids and the server
    // dedupes on them. Nutrition cannot, and pretending otherwise loses data.
    const fs = await import("node:fs/promises");
    const sources = await Promise.all(
      [
        "src/features/nutrition/api.ts",
        "src/features/nutrition/cache.ts",
        "src/features/nutrition/use-diary.ts",
      ].map((path) => fs.readFile(path, "utf8")),
    );

    for (const source of sources) {
      expect(source).not.toMatch(/from "@\/offline\/queue"|enqueue\(/);
    }
  });
});
