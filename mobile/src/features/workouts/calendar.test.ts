import { describe, expect, it, vi } from "vitest";

/**
 * The calendar grid and its intensity scale.
 *
 * Date arithmetic is where a calendar goes quietly wrong, and the failures are seasonal:
 * a month-shift bug only shows on the 31st, a leading-offset bug only on months starting
 * Sunday, and a UTC bug only for users west of Greenwich. None of them are visible on the
 * day you write the code, so they are pinned here instead.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error {},
}));

const {
  toLocalISO,
  monthBounds,
  monthGrid,
  shiftMonth,
  intensity,
  busiestVolume,
  monthTotals,
} = await import("./calendar-api");

function day(localDate: string, workoutCount: number, volume: string, seconds = 3600) {
  return { localDate, workoutCount, totalVolumeKg: volume, durationSeconds: seconds };
}

describe("local dates", () => {
  it("uses the device's day, not UTC", () => {
    // 00:30 in Athens is still the previous day in UTC. Building the grid from
    // toISOString() would move a late-night workout to the wrong square.
    expect(toLocalISO(new Date(2026, 7, 27, 0, 30))).toBe("2026-08-27");
  });

  it("pads single digits", () => {
    expect(toLocalISO(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("month bounds", () => {
  it("spans the first to the last day", () => {
    expect(monthBounds(new Date(2026, 7, 15))).toEqual({
      from: "2026-08-01",
      to: "2026-08-31",
    });
  });

  it("handles a 30-day month", () => {
    expect(monthBounds(new Date(2026, 8, 10)).to).toBe("2026-09-30");
  });

  it("handles February in a common year", () => {
    expect(monthBounds(new Date(2026, 1, 10)).to).toBe("2026-02-28");
  });

  it("handles February in a leap year", () => {
    expect(monthBounds(new Date(2028, 1, 10)).to).toBe("2028-02-29");
  });
});

describe("shifting months", () => {
  it("steps back and forward", () => {
    expect(monthBounds(shiftMonth(new Date(2026, 7, 15), -1)).from).toBe("2026-07-01");
    expect(monthBounds(shiftMonth(new Date(2026, 7, 15), 1)).from).toBe("2026-09-01");
  });

  it("does not skip a month when the current date is the 31st", () => {
    // The classic bug: adding a month to 31 January lands on 3 March, so paging forward
    // silently skips February entirely.
    expect(monthBounds(shiftMonth(new Date(2026, 0, 31), 1)).from).toBe("2026-02-01");
  });

  it("crosses a year boundary in both directions", () => {
    expect(monthBounds(shiftMonth(new Date(2026, 11, 15), 1)).from).toBe("2027-01-01");
    expect(monthBounds(shiftMonth(new Date(2026, 0, 15), -1)).from).toBe("2025-12-01");
  });
});

describe("the grid", () => {
  it("is always six weeks, so the layout never changes height", () => {
    // A calendar that grows and shrinks between months moves the controls under the
    // user's thumb as they page through it.
    for (const month of [0, 1, 4, 7, 11]) {
      expect(monthGrid(new Date(2026, month, 1))).toHaveLength(42);
    }
  });

  it("starts on Monday", () => {
    // Greece and the rest of Europe start the week on Monday; a Sunday-first grid reads
    // as an off-by-one to everybody the app is built for.
    const grid = monthGrid(new Date(2026, 7, 1)); // 1 Aug 2026 is a Saturday
    const first = new Date(2026, 7, 1);
    const leading = (first.getDay() + 6) % 7;
    expect(grid[leading]?.date).toBe("2026-08-01");
  });

  it("pads with the neighbouring months rather than blanks", () => {
    const grid = monthGrid(new Date(2026, 7, 1));
    expect(grid[0]?.inMonth).toBe(false);
    expect(grid.filter((cell) => cell.inMonth)).toHaveLength(31);
  });

  it("handles a month that begins on a Monday with no leading padding", () => {
    // 1 June 2026 is a Monday.
    const grid = monthGrid(new Date(2026, 5, 1));
    expect(grid[0]?.date).toBe("2026-06-01");
    expect(grid[0]?.inMonth).toBe(true);
  });

  it("produces consecutive dates with no gaps", () => {
    const grid = monthGrid(new Date(2026, 7, 1));
    for (let index = 1; index < grid.length; index += 1) {
      const previous = new Date(grid[index - 1]?.date ?? "");
      const current = new Date(grid[index]?.date ?? "");
      expect(current.getTime() - previous.getTime()).toBe(86_400_000);
    }
  });
});

describe("intensity", () => {
  it("is unlit for a rest day", () => {
    expect(intensity(undefined, 1000)).toBe(0);
    expect(intensity(day("2026-08-01", 0, "0"), 1000)).toBe(0);
  });

  it("scales relative to the busiest day rather than an absolute volume", () => {
    // "A heavy day" means something different for a beginner and a powerlifter. A fixed
    // scale paints one of them permanently grey.
    expect(intensity(day("2026-08-01", 1, "900"), 1000)).toBe(3);
    expect(intensity(day("2026-08-01", 1, "900"), 10000)).toBe(1);
  });

  it("lights a session that carried no volume", () => {
    // Mobility work or a run is still training. Showing it as a rest day is wrong.
    expect(intensity(day("2026-08-01", 1, "0"), 1000)).toBe(1);
  });

  it("never exceeds the top level", () => {
    expect(intensity(day("2026-08-01", 1, "99999"), 100)).toBe(3);
  });

  it("survives an unparseable volume", () => {
    expect(intensity(day("2026-08-01", 1, "nonsense"), 1000)).toBe(1);
  });
});

describe("month totals", () => {
  it("counts days trained, not workouts", () => {
    // Two sessions in one day is one day of training. Counting sessions would make a
    // double day look like two days of consistency.
    const totals = monthTotals([day("2026-08-01", 2, "1000"), day("2026-08-02", 0, "0")]);
    expect(totals.daysTrained).toBe(1);
  });

  it("sums volume and hours", () => {
    const totals = monthTotals([
      day("2026-08-01", 1, "1000", 3600),
      day("2026-08-02", 1, "500", 1800),
    ]);
    expect(totals.volumeKg).toBe(1500);
    expect(totals.hours).toBeCloseTo(1.5);
  });

  it("is all zeroes for an empty month", () => {
    expect(monthTotals([])).toEqual({ daysTrained: 0, volumeKg: 0, hours: 0 });
  });

  it("ignores an unparseable volume rather than producing NaN", () => {
    const totals = monthTotals([day("2026-08-01", 1, "x"), day("2026-08-02", 1, "100")]);
    expect(totals.volumeKg).toBe(100);
  });
});

describe("busiest volume", () => {
  it("finds the largest single day", () => {
    expect(busiestVolume([day("a", 1, "100"), day("b", 1, "900")])).toBe(900);
  });

  it("is zero for no days", () => {
    expect(busiestVolume([])).toBe(0);
  });
});
