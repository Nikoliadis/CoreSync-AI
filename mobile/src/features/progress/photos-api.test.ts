import { describe, expect, it, vi } from "vitest";

/**
 * The pure parts of the progress-photo client.
 *
 * The API client is mocked and the module imported dynamically, as everywhere else in
 * this suite: `@/lib/api/client` reaches native modules at import time, and those ship
 * as Flow-typed source that the test bundler cannot parse.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

const { defaultPair, spanLabel, weightDeltaLabel } = await import("./photos-api");
type Photo = Awaited<ReturnType<typeof import("./photos-api").photosApi.list>>[number];

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

describe("defaultPair", () => {
  it("picks the oldest and the newest", () => {
    // The ends of the range are the only pair that shows anything; two photos a week
    // apart show noise.
    const pair = defaultPair([
      photo({ id: "middle", localDate: "2026-05-01" }),
      photo({ id: "newest", localDate: "2026-08-01" }),
      photo({ id: "oldest", localDate: "2026-01-01" }),
    ]);
    expect(pair?.map((p) => p.id)).toEqual(["oldest", "newest"]);
  });

  it("skips a photo that is not ready", () => {
    // A pending photo has no URL at all — its EXIF has not been proven gone — so
    // pairing one would render a blank half.
    const pair = defaultPair([
      photo({ id: "a", localDate: "2026-01-01" }),
      photo({ id: "pending", localDate: "2026-08-01", isReady: false, url: null }),
      photo({ id: "b", localDate: "2026-04-01" }),
    ]);
    expect(pair?.map((p) => p.id)).toEqual(["a", "b"]);
  });

  it("is null when there is nothing to compare", () => {
    expect(defaultPair([])).toBeNull();
    expect(defaultPair([photo()])).toBeNull();
    expect(defaultPair([photo({ isReady: false }), photo({ id: "x", isReady: false })])).toBeNull();
  });

  it("leaves the list it was given alone", () => {
    const photos = [
      photo({ id: "b", localDate: "2026-08-01" }),
      photo({ id: "a", localDate: "2026-01-01" }),
    ];
    defaultPair(photos);
    expect(photos.map((p) => p.id)).toEqual(["b", "a"]);
  });
});

describe("spanLabel", () => {
  it("uses the largest unit that is not a lie", () => {
    expect(spanLabel(1)).toBe("1 day");
    expect(spanLabel(9)).toBe("9 days");
    expect(spanLabel(28)).toBe("4 weeks");
    expect(spanLabel(91)).toBe("3 months");
    expect(spanLabel(913)).toBe("2.5 years");
  });
});

describe("weightDeltaLabel", () => {
  it("signs the change explicitly", () => {
    // "2.5 kg" beside a photo comparison is ambiguous in the one direction that matters.
    expect(weightDeltaLabel("-2.50")).toBe("-2.5 kg");
    expect(weightDeltaLabel("1.20")).toBe("+1.2 kg");
  });

  it("says so when nothing changed", () => {
    expect(weightDeltaLabel("0.00")).toBe("no change");
    expect(weightDeltaLabel("0.04")).toBe("no change");
  });

  it("is null when a weight was never recorded", () => {
    expect(weightDeltaLabel(null)).toBeNull();
    // `Number("")` is 0, which would otherwise render "no change" for missing data —
    // the same bug that once put "0.0 kg" on the measurements screen.
    expect(weightDeltaLabel("")).toBeNull();
    expect(weightDeltaLabel("not a number")).toBeNull();
  });
});
