import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Progress: the number formatting and the chart's scale.
 *
 * The formatting carries more weight than formatting usually does. This screen tells
 * somebody whether months of effort did anything, and a dropped sign or a chart that
 * flattens the trend is not a cosmetic bug — it changes what they conclude and whether
 * they carry on.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

const { api } = await import("@/lib/api/client");
const { changeDirection, signedKg, weeklyRate, weightBounds, MEASUREMENT_SITES, SITE_LABELS } =
  await import("./api");

function point(localDate: string, weightKg: string, trendKg: string) {
  return { localDate, weightKg, trendKg };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("reading a change", () => {
  it("reports direction without judging it", () => {
    // Not "down is good". Someone gaining muscle wants this rising, and an app that
    // paints their success red teaches them to distrust it.
    expect(changeDirection("1.4")).toBe("up");
    expect(changeDirection("-1.4")).toBe("down");
  });

  it("treats scale noise as flat", () => {
    // 40 g is a glass of water, not a trend.
    expect(changeDirection("0.04")).toBe("flat");
    expect(changeDirection("-0.04")).toBe("flat");
  });

  it("is flat when there is nothing to compare", () => {
    expect(changeDirection(null)).toBe("flat");
    expect(changeDirection("nonsense")).toBe("flat");
  });
});

describe("formatting kilograms", () => {
  it("always carries the sign, because the sign is the message", () => {
    expect(signedKg("1.23")).toBe("+1.2 kg");
    expect(signedKg("-1.23")).toBe("−1.2 kg");
  });

  it("uses a real minus sign rather than a hyphen", () => {
    // At caption size a hyphen reads as a dash and the number looks positive.
    expect(signedKg("-2")).toContain("−");
    expect(signedKg("-2")).not.toContain("-");
  });

  it("says zero rather than a signed zero", () => {
    expect(signedKg("0")).toBe("0.0 kg");
    expect(signedKg("-0.01")).toBe("0.0 kg");
  });

  it("is a dash when there is no figure at all", () => {
    expect(signedKg(null)).toBe("—");
    expect(signedKg("")).toBe("—");
  });
});

describe("the weekly rate", () => {
  it("reads as a rate, to two places", () => {
    expect(weeklyRate("0.4")).toBe("+0.40 kg/week");
    expect(weeklyRate("-0.375")).toBe("−0.38 kg/week");
  });

  it("is absent rather than zero when there is no movement", () => {
    // "0.00 kg/week" from two weigh-ins reads as a finding. It is not one.
    expect(weeklyRate("0")).toBeNull();
    expect(weeklyRate(null)).toBeNull();
  });
});

describe("the chart scale", () => {
  it("spans both the dots and the trend line", () => {
    // One shared axis is the whole point: a trend on its own scale could look flat
    // beside wildly swinging dots, which is the comparison the chart exists to make.
    const bounds = weightBounds([point("2026-08-01", "82.0", "80.0")]);
    expect(bounds.min).toBeLessThanOrEqual(80);
    expect(bounds.max).toBeGreaterThanOrEqual(82);
  });

  it("gives a flat run a visible band instead of zero height", () => {
    // Otherwise the scale divides by zero and the path renders as NaN.
    const bounds = weightBounds([
      point("2026-08-01", "80.0", "80.0"),
      point("2026-08-02", "80.0", "80.0"),
    ]);
    expect(bounds.max - bounds.min).toBeGreaterThan(0);
  });

  it("pads a real range so points do not touch the edges", () => {
    const bounds = weightBounds([
      point("2026-08-01", "80.0", "80.0"),
      point("2026-08-02", "90.0", "90.0"),
    ]);
    expect(bounds.min).toBeLessThan(80);
    expect(bounds.max).toBeGreaterThan(90);
  });

  it("survives an empty series", () => {
    const bounds = weightBounds([]);
    expect(Number.isFinite(bounds.min)).toBe(true);
    expect(bounds.max).toBeGreaterThan(bounds.min);
  });

  it("ignores an unparseable reading rather than collapsing the scale", () => {
    const bounds = weightBounds([
      point("2026-08-01", "80.0", "80.0"),
      point("2026-08-02", "not-a-number", "81.0"),
    ]);
    expect(Number.isFinite(bounds.min)).toBe(true);
    expect(Number.isFinite(bounds.max)).toBe(true);
  });
});

describe("measurement sites", () => {
  it("every site has a label, so none can render as a raw key", () => {
    for (const site of MEASUREMENT_SITES) {
      expect(SITE_LABELS[site]).toBeTruthy();
    }
  });

  it("is ordered the way a person measures, top down", () => {
    expect(MEASUREMENT_SITES[0]).toBe("neck");
    expect(MEASUREMENT_SITES.at(-1)).toBe("rightCalf");
  });
});

describe("the API contract", () => {
  it("asks for a window rather than the whole history", async () => {
    vi.mocked(api.get).mockResolvedValue({ points: [] });
    const { progressApi } = await import("./api");
    await progressApi.weight(30);

    const [path, options] = vi.mocked(api.get).mock.calls[0] as [
      string,
      { query: { from: string } },
    ];
    expect(path).toBe("/v1/progress/weight");
    expect(options.query.from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("sends only the sites that were filled in", async () => {
    // The server keeps the previous value for anything omitted, which is what lets
    // somebody log just their waist without wiping the other nine.
    vi.mocked(api.post).mockResolvedValue({});
    const { progressApi } = await import("./api");
    await progressApi.logMeasurement({ waist: 84 });

    const [, body] = vi.mocked(api.post).mock.calls[0] as [string, Record<string, unknown>];
    expect(Object.keys(body)).toEqual(["waist"]);
  });
});
