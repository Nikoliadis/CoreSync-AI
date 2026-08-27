import * as Sentry from "@sentry/react-native";

/**
 * Crash and error reporting.
 *
 * The point of this is a single number: crash-free sessions, which docs/15 sets at
 * >99.5% as a Phase 6 exit criterion. That figure cannot be claimed, estimated or
 * inferred — it can only be measured, and until this is reporting from real installs
 * nobody is entitled to say anything about it.
 *
 * **Privacy.** A fitness app holds bodyweight, measurements, food diaries and coaching
 * conversations. None of that belongs in a crash report, and none of it is sent:
 * `sendDefaultPii` is off, request bodies are stripped, and the only user identifier
 * attached is the account id — an opaque UUID that means nothing without our database,
 * and which is what makes "how many people did this affect" answerable at all.
 *
 * **Production only.** A development crash is a crash somebody is already looking at.
 * Reporting it costs quota and pollutes the very metric this exists to measure.
 */

const DSN = process.env.EXPO_PUBLIC_SENTRY_DSN ?? "";

/** `production` builds report. Everything else stays local. */
function environment(): string {
  return process.env.EXPO_PUBLIC_ENVIRONMENT ?? (__DEV__ ? "development" : "production");
}

export function isCrashReportingEnabled(): boolean {
  // No DSN is a legitimate state, not a misconfiguration: a self-hosted or offline build
  // has nowhere to send. It must degrade to silence rather than throwing on launch.
  return Boolean(DSN) && !__DEV__;
}

/**
 * Strip anything that could carry personal data out of an event.
 *
 * Deliberately an allow-nothing approach for request bodies rather than an attempt to
 * redact fields by name: a redactor that works from a list of known keys misses the one
 * added last week, and the failure is invisible until somebody's diary is in a bug
 * report.
 */
// Generic over the event type so it satisfies `beforeSend`, whose parameter is the
// narrower `ErrorEvent` that the React Native package does not re-export.
function scrub<T extends Sentry.Event>(event: T): T {
  if (event.request) {
    delete event.request.data;
    delete event.request.cookies;
    if (event.request.headers) {
      delete event.request.headers.Authorization;
      delete event.request.headers.authorization;
    }
  }

  // The account id is kept; everything else about the person is not. Email or display
  // name in a crash report is personal data leaving the device for no diagnostic gain.
  if (event.user) {
    event.user = { id: event.user.id };
  }

  return event;
}

export function initCrashReporting(): void {
  if (!isCrashReportingEnabled()) return;

  Sentry.init({
    dsn: DSN,
    environment: environment(),
    // Stamped so a crash can be traced to the build it came from. Without this, "is the
    // fix out yet" is unanswerable.
    release: process.env.EXPO_PUBLIC_APP_VERSION ?? "dev",

    // Never. This is what would attach IP addresses and device identifiers.
    sendDefaultPii: false,

    // Errors only. Performance tracing on a fitness app samples screens full of personal
    // numbers and is not what the exit criterion asks for.
    tracesSampleRate: 0,

    // Breadcrumbs are the most useful part of a report and the easiest place for data to
    // leak, because console output during development often contains real values.
    maxBreadcrumbs: 50,

    beforeSend: (event) => scrub(event),

    beforeBreadcrumb: (breadcrumb) => {
      // Console breadcrumbs carry whatever was logged, which in this app includes API
      // payloads. Navigation and lifecycle breadcrumbs are what actually help.
      if (breadcrumb.category === "console") return null;
      return breadcrumb;
    },
  });
}

/**
 * Attach the signed-in account, so a crash count can become "how many people".
 *
 * The id only. Resolving it to a person requires our database, which is the property that
 * makes it safe to send.
 */
export function identifyUser(userId: string | null): void {
  if (!isCrashReportingEnabled()) return;
  Sentry.setUser(userId ? { id: userId } : null);
}

/**
 * Report something caught.
 *
 * For failures the app handles but should not be having — a sync flush that exhausted
 * its retries, a local database write that failed. An uncaught crash needs no help.
 */
export function reportError(error: unknown, context?: Record<string, string>): void {
  if (!isCrashReportingEnabled()) {
    // Still visible to whoever is running the app, which is the point in development.
    console.warn("error", error, context);
    return;
  }
  Sentry.captureException(error, context ? { tags: context } : undefined);
}

/** Wraps the root component so native crashes and unhandled JS errors are captured. */
export const withCrashReporting = Sentry.wrap;
