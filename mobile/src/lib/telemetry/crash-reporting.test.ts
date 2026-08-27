import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * What crash reporting is allowed to send.
 *
 * A fitness app holds bodyweight, measurements, food diaries and coaching conversations.
 * A crash reporter is the easiest place for that to leave the device, because it collects
 * context automatically and nobody reads the payload afterwards.
 *
 * These tests are the check on that. They assert the scrubbing that keeps personal data
 * out and the account id in — the id is what turns "twelve crashes" into "twelve people",
 * and it means nothing to anybody without our database.
 */

const sentry = vi.hoisted(() => ({
  init: vi.fn(),
  setUser: vi.fn(),
  captureException: vi.fn(),
  wrap: vi.fn((component: unknown) => component),
}));

vi.mock("@sentry/react-native", () => sentry);

const globals = globalThis as unknown as { __DEV__: boolean };

async function load(env: Record<string, string | undefined>, dev = false) {
  vi.resetModules();
  vi.clearAllMocks();
  globals.__DEV__ = dev;
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  return import("./crash-reporting");
}

/** The options Sentry was initialised with, for asserting configuration. */
function options(): Record<string, unknown> {
  return (sentry.init.mock.calls[0]?.[0] ?? {}) as Record<string, unknown>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("when reporting is enabled", () => {
  it("initialises with a DSN in a production build", async () => {
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" });

    module.initCrashReporting();
    expect(sentry.init).toHaveBeenCalledOnce();
  });

  it("never sends default PII", async () => {
    // This is the setting that would attach IP addresses and device identifiers.
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" });
    module.initCrashReporting();

    expect(options().sendDefaultPii).toBe(false);
  });

  it("does not sample performance traces", async () => {
    // Tracing on this app would sample screens full of somebody's personal numbers, and
    // is not what the crash-free exit criterion asks for.
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" });
    module.initCrashReporting();

    expect(options().tracesSampleRate).toBe(0);
  });

  it("stamps the release so a crash can be traced to a build", async () => {
    const module = await load({
      EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1",
      EXPO_PUBLIC_APP_VERSION: "1.4.2",
    });
    module.initCrashReporting();

    expect(options().release).toBe("1.4.2");
  });

  it("records the environment so production is separable", async () => {
    const module = await load({
      EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1",
      EXPO_PUBLIC_ENVIRONMENT: "staging",
    });
    module.initCrashReporting();

    expect(options().environment).toBe("staging");
  });
});

describe("when reporting is disabled", () => {
  it("stays silent in development even with a DSN", async () => {
    // A development crash is one somebody is already looking at. Reporting it costs
    // quota and pollutes the metric this exists to measure.
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" }, true);

    module.initCrashReporting();
    expect(sentry.init).not.toHaveBeenCalled();
    expect(module.isCrashReportingEnabled()).toBe(false);
  });

  it("stays silent with no DSN, rather than throwing on launch", async () => {
    // A self-hosted or offline build has nowhere to send. That is a legitimate state.
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: undefined });

    expect(() => {
      module.initCrashReporting();
    }).not.toThrow();
    expect(sentry.init).not.toHaveBeenCalled();
  });

  it("still surfaces a handled error locally", async () => {
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: undefined });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    module.reportError(new Error("something"));

    expect(sentry.captureException).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("does not identify a user when it cannot report", async () => {
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: undefined });
    module.identifyUser("user-1");

    expect(sentry.setUser).not.toHaveBeenCalled();
  });
});

describe("scrubbing an event", () => {
  async function scrubbed(event: Record<string, unknown>) {
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" });
    module.initCrashReporting();
    const beforeSend = options().beforeSend as (e: unknown) => Record<string, unknown>;
    return beforeSend(event);
  }

  it("removes the request body", async () => {
    // Where a food diary, a weight or a coaching message would be.
    const event = await scrubbed({
      request: { data: { weightKg: 82.4, note: "felt awful today" } },
    });

    expect((event.request as Record<string, unknown>).data).toBeUndefined();
  });

  it("removes the Authorization header", async () => {
    const event = await scrubbed({
      request: { headers: { Authorization: "Bearer secret", "X-Client-Version": "1.0" } },
    });

    const headers = (event.request as { headers: Record<string, unknown> }).headers;
    expect(headers.Authorization).toBeUndefined();
    // Harmless diagnostic context is kept — scrubbing is not the same as blinding.
    expect(headers["X-Client-Version"]).toBe("1.0");
  });

  it("removes cookies", async () => {
    const event = await scrubbed({ request: { cookies: "refresh=abc" } });
    expect((event.request as Record<string, unknown>).cookies).toBeUndefined();
  });

  it("keeps the account id but nothing else about the person", async () => {
    // The id is what makes "how many people did this affect" answerable, and it means
    // nothing without our database. An email in a crash report is personal data leaving
    // the device for no diagnostic gain.
    const event = await scrubbed({
      user: { id: "user-1", email: "nikos@example.com", username: "nikos" },
    });

    expect(event.user).toEqual({ id: "user-1" });
  });

  it("passes an event with nothing sensitive through untouched", async () => {
    const event = await scrubbed({ message: "boom" });
    expect(event.message).toBe("boom");
  });

  it("drops console breadcrumbs, which carry whatever was logged", async () => {
    const module = await load({ EXPO_PUBLIC_SENTRY_DSN: "https://key@example.test/1" });
    module.initCrashReporting();
    const beforeBreadcrumb = options().beforeBreadcrumb as (b: unknown) => unknown;

    expect(beforeBreadcrumb({ category: "console", message: "diary: 2200 kcal" })).toBeNull();
    expect(beforeBreadcrumb({ category: "navigation" })).not.toBeNull();
  });
});
