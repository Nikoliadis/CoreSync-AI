import { describe, expect, it } from "vitest";

import {
  byPose,
  defaultPair,
  type Photo,
  spanLabel,
  weightDeltaLabel,
} from "./photos-api";

function photo(overrides: Partial<Photo> = {}): Photo {
  return {
    id: "p1",
    localDate: "2026-08-01",
    pose: "front",
    processingStatus: "ready",
    isReady: true,
    url: "https://storage.test/read/p1",
    thumbnailUrl: "https://storage.test/read/p1_thumb",
    urlExpiresAt: "2026-08-01T12:05:00Z",
    width: 900,
    height: 1200,
    weightAtCaptureKg: "80.00",
    note: null,
    ...overrides,
  };
}

describe("byPose", () => {
  it("keeps each pose separate", () => {
    const grouped = byPose([
      photo({ id: "a", pose: "front" }),
      photo({ id: "b", pose: "back" }),
      photo({ id: "c", pose: "front" }),
    ]);
    expect(grouped.get("front")?.map((p) => p.id)).toEqual(["a", "c"]);
    expect(grouped.get("back")).toHaveLength(1);
  });

  it("is empty for an empty timeline", () => {
    expect(byPose([]).size).toBe(0);
  });
});

describe("defaultPair", () => {
  it("picks the oldest and the newest", () => {
    // The ends of the range are the only pair that shows anything. Two photos a week
    // apart show noise.
    const pair = defaultPair([
      photo({ id: "middle", localDate: "2026-05-01" }),
      photo({ id: "newest", localDate: "2026-08-01" }),
      photo({ id: "oldest", localDate: "2026-01-01" }),
    ]);
    expect(pair?.map((p) => p.id)).toEqual(["oldest", "newest"]);
  });

  it("ignores photos that are not ready", () => {
    // A pending photo has no URL at all, so pairing one would render a broken half.
    const pair = defaultPair([
      photo({ id: "ready-a", localDate: "2026-01-01" }),
      photo({ id: "pending", localDate: "2026-08-01", isReady: false, url: null }),
      photo({ id: "ready-b", localDate: "2026-04-01" }),
    ]);
    expect(pair?.map((p) => p.id)).toEqual(["ready-a", "ready-b"]);
  });

  it("is null when there is nothing to compare", () => {
    expect(defaultPair([])).toBeNull();
    expect(defaultPair([photo()])).toBeNull();
    expect(defaultPair([photo({ isReady: false }), photo({ id: "x", isReady: false })])).toBeNull();
  });

  it("does not mutate the list it was given", () => {
    const photos = [photo({ id: "b", localDate: "2026-08-01" }), photo({ id: "a", localDate: "2026-01-01" })];
    defaultPair(photos);
    expect(photos.map((p) => p.id)).toEqual(["b", "a"]);
  });
});

describe("spanLabel", () => {
  it("uses days for a short gap", () => {
    expect(spanLabel(1)).toBe("1 day");
    expect(spanLabel(9)).toBe("9 days");
  });

  it("uses weeks in between", () => {
    expect(spanLabel(28)).toBe("4 weeks");
  });

  it("uses months for the usual case", () => {
    expect(spanLabel(91)).toBe("3 months");
  });

  it("uses years beyond two", () => {
    expect(spanLabel(913)).toBe("2.5 years");
  });

  it("handles zero", () => {
    expect(spanLabel(0)).toBe("0 days");
  });
});

describe("weightDeltaLabel", () => {
  it("signs a loss and a gain explicitly", () => {
    // "2.5 kg" beside a photo comparison is ambiguous in the one direction that matters.
    expect(weightDeltaLabel("-2.50")).toBe("-2.5 kg");
    expect(weightDeltaLabel("1.20")).toBe("+1.2 kg");
  });

  it("says so when nothing changed", () => {
    expect(weightDeltaLabel("0.00")).toBe("no change");
    // Rounds to zero rather than rendering "+0.0 kg", which reads as a gain.
    expect(weightDeltaLabel("0.04")).toBe("no change");
  });

  it("is null when a weight was never recorded", () => {
    expect(weightDeltaLabel(null)).toBeNull();
    // `Number("")` is 0, which would render "no change" for missing data.
    expect(weightDeltaLabel("")).toBeNull();
    expect(weightDeltaLabel("not a number")).toBeNull();
  });
});
