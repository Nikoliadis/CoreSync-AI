import { describe, expect, it } from "vitest";

import {
  busiestVolume,
  type CalendarDay,
  type CalendarSession,
  intensity,
  longestStreak,
  monthBounds,
  monthGrid,
  monthTotals,
  sessionsByDate,
  shiftMonth,
  toLocalISO,
} from "./calendar-api";

/**
 * A calendar is arithmetic pretending to be a UI, and every one of these covers a case
 * that is invisible eleven months of the year.
 */

function day(localDate: string, overrides: Partial<CalendarDay> = {}): CalendarDay {
  return {
    localDate,
    workoutCount: 1,
    totalVolumeKg: "1000",
    durationSeconds: 3600,
    ...overrides,
  };
}

describe("toLocalISO", () => {
  it("uses the local date, not the UTC one", () => {
    // 23:30 on the 27th in a positive-offset zone is still the 27th. `toISOString`
    // would say the 27th too here, but the point is that this never consults UTC at all.
    expect(toLocalISO(new Date(2026, 7, 27, 23, 30))).toBe("2026-08-27");
  });

  it("pads single-digit months and days", () => {
    expect(toLocalISO(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("monthBounds", () => {
  it("covers the whole month", () => {
    expect(monthBounds(new Date(2026, 7, 15))).toEqual({ from: "2026-08-01", to: "2026-08-31" });
  });

  it("gets February right in a leap year", () => {
    expect(monthBounds(new Date(2028, 1, 10))).toEqual({ from: "2028-02-01", to: "2028-02-29" });
  });

  it("gets February right in a common year", () => {
    expect(monthBounds(new Date(2026, 1, 10))).toEqual({ from: "2026-02-01", to: "2026-02-28" });
  });
});

describe("shiftMonth", () => {
  it("does not skip a month when the current date is the 31st", () => {
    // The bug this exists for: from 31 January, `setMonth(+1)` overflows into March.
    expect(monthBounds(shiftMonth(new Date(2026, 0, 31), 1)).from).toBe("2026-02-01");
  });

  it("crosses the year boundary in both directions", () => {
    expect(monthBounds(shiftMonth(new Date(2026, 11, 15), 1)).from).toBe("2027-01-01");
    expect(monthBounds(shiftMonth(new Date(2026, 0, 15), -1)).from).toBe("2025-12-01");
  });
});

describe("monthGrid", () => {
  it("is always six rows, so the page does not change height", () => {
    for (const month of [0, 1, 4, 7, 11]) {
      expect(monthGrid(new Date(2026, month, 1))).toHaveLength(42);
    }
  });

  it("starts the week on Monday", () => {
    // 1 August 2026 is a Saturday, so the row begins on Monday 27 July.
    expect(monthGrid(new Date(2026, 7, 1))[0]).toEqual({
      date: "2026-07-27",
      day: 27,
      inMonth: false,
    });
  });

  it("needs no leading blanks when the month starts on a Monday", () => {
    // 1 June 2026 is a Monday.
    const cells = monthGrid(new Date(2026, 5, 1));
    expect(cells[0]).toEqual({ date: "2026-06-01", day: 1, inMonth: true });
  });

  it("puts a Sunday-starting month at the end of the first row", () => {
    // 1 February 2026 is a Sunday — the Monday-first case most likely to be off by one.
    const cells = monthGrid(new Date(2026, 1, 1));
    expect(cells[6]).toEqual({ date: "2026-02-01", day: 1, inMonth: true });
    expect(cells[0].date).toBe("2026-01-26");
  });

  it("marks days either side of the month as out of it", () => {
    const cells = monthGrid(new Date(2026, 7, 1));
    const inMonth = cells.filter((cell) => cell.inMonth);
    expect(inMonth).toHaveLength(31);
    expect(inMonth[0].date).toBe("2026-08-01");
    expect(inMonth[30].date).toBe("2026-08-31");
  });
});

describe("intensity", () => {
  const busiest = 9000;

  it("is 0 for a day with no workout", () => {
    expect(intensity(undefined, busiest)).toBe(0);
    expect(intensity(day("2026-08-01", { workoutCount: 0 }), busiest)).toBe(0);
  });

  it("lights a session that logged no volume", () => {
    // Mobility, a run, a stretch. It happened, so it must not read as a rest day.
    expect(intensity(day("2026-08-01", { totalVolumeKg: "0" }), busiest)).toBe(1);
  });

  it("scales relative to the busiest day in view", () => {
    expect(intensity(day("2026-08-01", { totalVolumeKg: "1000" }), busiest)).toBe(1);
    expect(intensity(day("2026-08-02", { totalVolumeKg: "5000" }), busiest)).toBe(2);
    expect(intensity(day("2026-08-03", { totalVolumeKg: "9000" }), busiest)).toBe(3);
  });

  it("survives a volume that is not a number", () => {
    expect(intensity(day("2026-08-01", { totalVolumeKg: "" }), busiest)).toBe(1);
  });

  it("does not divide by zero when nothing has volume", () => {
    expect(intensity(day("2026-08-01", { totalVolumeKg: "0" }), 0)).toBe(1);
  });
});

describe("busiestVolume", () => {
  it("is zero for an empty month rather than -Infinity", () => {
    expect(busiestVolume([])).toBe(0);
  });

  it("ignores unparseable volumes", () => {
    expect(busiestVolume([day("a", { totalVolumeKg: "" }), day("b", { totalVolumeKg: "42" })])).toBe(
      42,
    );
  });
});

describe("monthTotals", () => {
  it("counts days trained, not sessions", () => {
    // Two workouts on one day is one day trained. Counting sessions would inflate the
    // headline number for anyone who trains twice on a Saturday.
    const totals = monthTotals([
      day("2026-08-01", { workoutCount: 2, totalVolumeKg: "1000", durationSeconds: 1800 }),
      day("2026-08-02", { workoutCount: 0, totalVolumeKg: "0", durationSeconds: 0 }),
      day("2026-08-03", { workoutCount: 1, totalVolumeKg: "500", durationSeconds: 1800 }),
    ]);
    expect(totals.daysTrained).toBe(2);
    expect(totals.volumeKg).toBe(1500);
    expect(totals.hours).toBe(1);
  });

  it("is all zeroes for a month with nothing in it", () => {
    expect(monthTotals([])).toEqual({ daysTrained: 0, volumeKg: 0, hours: 0 });
  });
});

describe("sessionsByDate", () => {
  const session = (id: string, localDate: string): CalendarSession => ({
    id,
    name: "Push",
    localDate,
    totalVolumeKg: "1000",
    totalSets: 12,
    exerciseCount: 4,
    prCount: 0,
    durationSeconds: 3600,
  });

  it("groups more than one session on the same day", () => {
    const map = sessionsByDate([
      session("evening", "2026-08-01"),
      session("morning", "2026-08-01"),
      session("other", "2026-08-02"),
    ]);
    expect(map.get("2026-08-01")?.map((s) => s.id)).toEqual(["evening", "morning"]);
    expect(map.get("2026-08-02")).toHaveLength(1);
  });

  it("has nothing for a day that was not trained", () => {
    expect(sessionsByDate([]).get("2026-08-01")).toBeUndefined();
  });
});

describe("longestStreak", () => {
  it("counts consecutive trained days", () => {
    expect(
      longestStreak([day("2026-08-01"), day("2026-08-02"), day("2026-08-03")]),
    ).toBe(3);
  });

  it("breaks on a rest day", () => {
    expect(
      longestStreak([
        day("2026-08-01"),
        day("2026-08-02"),
        day("2026-08-04"),
        day("2026-08-05"),
        day("2026-08-06"),
      ]),
    ).toBe(3);
  });

  it("crosses a month boundary correctly", () => {
    // The day arithmetic must not assume 31-day months, or a streak spanning the end of
    // February silently ends there.
    expect(longestStreak([day("2026-02-27"), day("2026-02-28"), day("2026-03-01")])).toBe(3);
  });

  it("ignores days with a zero workout count", () => {
    expect(
      longestStreak([day("2026-08-01"), day("2026-08-02", { workoutCount: 0 }), day("2026-08-03")]),
    ).toBe(1);
  });

  it("is zero for a month with no training", () => {
    expect(longestStreak([])).toBe(0);
    expect(longestStreak([day("2026-08-01", { workoutCount: 0 })])).toBe(0);
  });

  it("does not depend on the order the server returns", () => {
    expect(longestStreak([day("2026-08-03"), day("2026-08-01"), day("2026-08-02")])).toBe(3);
  });
});
