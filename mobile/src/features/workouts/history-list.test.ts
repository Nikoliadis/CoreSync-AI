import { describe, expect, it, vi } from "vitest";

/**
 * The workout history list.
 *
 * The date helper is the one with teeth. `new Date("2026-08-25")` parses as midnight
 * *UTC*, which is the previous evening for anyone west of Greenwich — so a workout logged
 * on the 25th would be labelled the 24th. The server sends `localDate` precisely so the
 * client does not have to guess a timezone; parsing it as UTC throws that away.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error {},
}));

const { relativeDay, duration, volume } = await import("./history-list-api");

describe("naming the day", () => {
  const today = new Date(2026, 7, 25);

  it("names today and yesterday", () => {
    expect(relativeDay("2026-08-25", today)).toBe("Today");
    expect(relativeDay("2026-08-24", today)).toBe("Yesterday");
  });

  it("shows a date beyond that, because 'six days ago' stops helping", () => {
    expect(relativeDay("2026-08-18", today)).not.toMatch(/ago|Today|Yesterday/);
  });

  it("does not drift a day west of Greenwich", () => {
    // The bug this guards: parsing as UTC and rendering local shows the 24th.
    const rendered = relativeDay("2026-08-20", today);
    expect(rendered).toContain("20");
  });

  it("crosses a month boundary", () => {
    expect(relativeDay("2026-08-01", new Date(2026, 7, 2))).toBe("Yesterday");
  });

  it("crosses a year boundary", () => {
    expect(relativeDay("2025-12-31", new Date(2026, 0, 1))).toBe("Yesterday");
  });

  it("returns the raw value rather than throwing on a malformed date", () => {
    expect(relativeDay("not-a-date", today)).toBe("not-a-date");
  });
});

describe("duration", () => {
  it("reads in minutes below an hour", () => {
    expect(duration(48 * 60)).toBe("48m");
  });

  it("splits hours out above one", () => {
    expect(duration(3600 + 12 * 60)).toBe("1h 12m");
  });

  it("is a dash when the session never recorded one", () => {
    expect(duration(null)).toBe("—");
    expect(duration(0)).toBe("—");
  });
});

describe("volume", () => {
  it("rounds and groups, because 12450.00 does not read", () => {
    expect(volume("12450.00")).toBe(`${(12450).toLocaleString()} kg`);
  });

  it("is a dash for a bodyweight-only session", () => {
    expect(volume("0.00")).toBe("—");
  });

  it("is a dash rather than NaN on a malformed value", () => {
    expect(volume("")).toBe("—");
  });
});
