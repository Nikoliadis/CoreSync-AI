import { describe, expect, it, vi } from "vitest";

/**
 * Notifications: category toggles and relative time.
 *
 * The toggle logic is the part that can lose data. The API takes the complete set of
 * enabled categories rather than a delta, so every toggle rewrites the whole list — and
 * a naive implementation drops any category the client does not know about, silently
 * turning off something the server added after this build shipped.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  ApiError: class extends Error {},
}));

const {
  toggleCategory,
  quietHoursLabel,
  relativeTime,
  routeFor,
  CATEGORIES,
  CATEGORY_LABELS,
  CATEGORY_BLURBS,
} = await import("./api");

function notification(overrides: Partial<import("./api").Notification> = {}) {
  return {
    id: "n1",
    category: "pr_celebration",
    title: "New record",
    body: "You beat your bench press.",
    deepLink: null,
    data: {},
    readAt: null,
    createdAt: "2026-08-27T10:00:00Z",
    isRead: false,
    ...overrides,
  };
}

describe("toggling a category", () => {
  it("adds one that was off", () => {
    expect(toggleCategory(["pr_celebration"], "weekly_report", true)).toContain("weekly_report");
  });

  it("removes one that was on", () => {
    expect(toggleCategory(["pr_celebration", "weekly_report"], "weekly_report", false)).toEqual([
      "pr_celebration",
    ]);
  });

  it("does not duplicate a category already enabled", () => {
    const result = toggleCategory(["pr_celebration"], "pr_celebration", true);
    expect(result.filter((item) => item === "pr_celebration")).toHaveLength(1);
  });

  it("keeps a category this build does not know about", () => {
    // The server may add one before the client ships. Dropping it here would silently
    // turn off something the user had enabled elsewhere.
    const result = toggleCategory(["pr_celebration", "future_thing"], "weekly_report", true);
    expect(result).toContain("future_thing");
  });

  it("orders known categories canonically so the payload is stable", () => {
    const a = toggleCategory(["weekly_report", "pr_celebration"], "streak_risk", true);
    const b = toggleCategory(["pr_celebration", "weekly_report"], "streak_risk", true);
    expect(a).toEqual(b);
  });

  it("turning everything off yields an empty list, not a missing field", () => {
    expect(toggleCategory(["pr_celebration"], "pr_celebration", false)).toEqual([]);
  });

  it("never offers a toggle for system messages", () => {
    // Account and security notices are not a preference. A switch that does not switch
    // anything is worse than no switch.
    expect(CATEGORIES).not.toContain("system");
  });

  it("every category has a label and a blurb", () => {
    for (const category of CATEGORIES) {
      expect(CATEGORY_LABELS[category]).toBeTruthy();
      expect(CATEGORY_BLURBS[category]).toBeTruthy();
    }
  });
});

describe("quiet hours", () => {
  function prefs(start: number | null, end: number | null) {
    return {
      enabledCategories: [],
      pushEnabled: true,
      emailEnabled: true,
      quietHoursStart: start,
      quietHoursEnd: end,
    };
  }

  it("reads as a range", () => {
    expect(quietHoursLabel(prefs(22, 7))).toBe("22:00 – 07:00");
  });

  it("pads single-digit hours", () => {
    expect(quietHoursLabel(prefs(9, 8))).toBe("09:00 – 08:00");
  });

  it("is absent when not set", () => {
    expect(quietHoursLabel(prefs(null, null))).toBeNull();
    expect(quietHoursLabel(undefined)).toBeNull();
  });

  it("treats a half-set range as unset rather than rendering null", () => {
    expect(quietHoursLabel(prefs(22, null))).toBeNull();
  });
});

describe("relative time", () => {
  const now = Date.parse("2026-08-27T12:00:00Z");

  it("says just now for the last minute", () => {
    expect(relativeTime("2026-08-27T11:59:30Z", now)).toBe("just now");
  });

  it("counts minutes, hours and days", () => {
    expect(relativeTime("2026-08-27T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-08-27T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-08-25T12:00:00Z", now)).toBe("2d ago");
  });

  it("switches to a date beyond a week", () => {
    expect(relativeTime("2026-08-01T12:00:00Z", now)).not.toContain("ago");
  });

  it("never reports a negative age from a clock that is ahead", () => {
    expect(relativeTime("2026-08-27T12:05:00Z", now)).toBe("just now");
  });

  it("is empty rather than NaN on a malformed timestamp", () => {
    expect(relativeTime("nonsense", now)).toBe("");
    expect(relativeTime(null, now)).toBe("");
  });
});

describe("following a notification", () => {
  it("follows an app-relative link", () => {
    expect(routeFor(notification({ deepLink: "/workout/abc" }))).toBe("/workout/abc");
  });

  it("does nothing when there is no link", () => {
    expect(routeFor(notification())).toBeNull();
  });

  it("refuses an external link rather than guessing", () => {
    // Landing on the wrong screen is worse than landing nowhere: the user has to work
    // out where they are before they can get back.
    expect(routeFor(notification({ deepLink: "https://example.com/x" }))).toBeNull();
  });
});
