import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/layout/logo";

/**
 * The public privacy policy.
 *
 * Deliberately outside the `(app)` group, so it renders with no session and no
 * `AuthGuard` — app-store reviewers and anyone comparing apps read this before they have
 * an account, and a policy behind a login is a policy nobody can check.
 *
 * Everything below was written from the actual schema and code rather than from a
 * template: the tables that exist, the columns that hold personal data, the thirty-day
 * grace period the erasure job really enforces, and the scrubbing the crash reporter
 * really performs. Where behaviour is configuration-dependent it says so instead of
 * promising.
 *
 * IT HAS NOT BEEN REVIEWED BY A LAWYER. The banner at the top says so, and it must stay
 * there until one has read it — a policy that claims a legal review it never had is worse
 * than an obviously draft one.
 */

export const metadata: Metadata = {
  title: "Privacy policy",
  description:
    "What CoreSync collects, why, where it goes, and how to get rid of it.",
};

const UPDATED = "27 August 2026";

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="mb-3 text-xl font-semibold tracking-tight text-text sm:text-2xl">
        {title}
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-text-secondary sm:text-base">
        {children}
      </div>
    </section>
  );
}

function DataRow({ what, why }: { what: string; why: string }) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-3 pr-4 align-top font-medium text-text">{what}</td>
      <td className="py-3 align-top text-text-secondary">{why}</td>
    </tr>
  );
}

export default function PrivacyPolicyPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8 sm:py-16">
      <header className="mb-10">
        <Link href="/" className="inline-block" aria-label="CoreSync home">
          <Logo />
        </Link>
        <h1 className="mt-8 text-3xl font-bold tracking-tight text-text sm:text-4xl">
          Privacy policy
        </h1>
        <p className="mt-2 text-sm text-text-muted">Last updated {UPDATED}</p>
      </header>

      <div
        role="note"
        className="mb-10 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm leading-relaxed text-text"
      >
        <p className="font-semibold">Draft — pending legal review</p>
        <p className="mt-1 text-text-secondary">
          This describes what the software actually does, written from the code and the
          database schema. It has <strong>not</strong> been reviewed by a lawyer and is
          not a statement of legal compliance. If you are evaluating CoreSync for
          anything that depends on that, ask us for the reviewed version.
        </p>
      </div>

      <div className="space-y-10">
        <Section id="summary" title="The short version">
          <ul className="list-disc space-y-2 pl-5">
            <li>
              We collect what the app needs to work: your account, what you train, what
              you eat, and what you weigh.
            </li>
            <li>We do not sell it, and we do not run advertising.</li>
            <li>
              You can delete your account from inside the app. It is anonymised
              permanently after thirty days.
            </li>
            <li>
              The AI coach sends your relevant training data to Microsoft Azure OpenAI to
              answer a question. It is <strong>not</strong> used to train any model
              unless you switch that on yourself, and it is off by default.
            </li>
          </ul>
        </Section>

        <Section id="what" title="What we collect">
          <p>Only what you give us or what the app produces as you use it.</p>
          <div className="-mx-2 overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="py-2 pr-4 font-semibold text-text">Data</th>
                  <th className="py-2 font-semibold text-text">Why we hold it</th>
                </tr>
              </thead>
              <tbody>
                <DataRow
                  what="Email address"
                  why="Signing in, verifying the account, and sending you account and security messages."
                />
                <DataRow
                  what="Password"
                  why="Stored only as a one-way hash. We cannot read it and cannot recover it for you."
                />
                <DataRow
                  what="Name, date of birth, gender, height"
                  why="Calculating your calorie and macro targets. Age, height and sex are inputs to the formula — without them we cannot produce a number."
                />
                <DataRow
                  what="Workouts, sets, weights, personal records"
                  why="The product. Also what the coach reads to answer questions about your training."
                />
                <DataRow
                  what="Food diary, water, recipes"
                  why="Nutrition tracking and daily totals."
                />
                <DataRow
                  what="Bodyweight, body measurements, progress photos"
                  why="Trends over time. Photos have their EXIF metadata stripped on upload, so the location where they were taken is removed."
                />
                <DataRow
                  what="Coach conversations"
                  why="So a conversation has history and you can read it again later."
                />
                <DataRow
                  what="IP address and browser or device description"
                  why="Recorded against each sign-in session so you can recognise an unfamiliar one, and so we can shut down abuse. Attached to sessions only, not to your training data."
                />
                <DataRow
                  what="Device push token"
                  why="Sending notifications to your phone. Only stored once you allow notifications, and removed when you sign out."
                />
              </tbody>
            </table>
          </div>
          <p>
            We do not collect contacts, location, health data from Apple Health or Google
            Fit, or anything from other apps on your device.
          </p>
        </Section>

        <Section id="ai" title="The AI coach">
          <p>
            When you ask the coach something, we send your question along with the
            relevant slice of your own data — recent sessions, your targets, your recent
            weight — to <strong>Microsoft Azure OpenAI</strong>, which generates the
            answer. Azure processes it under Microsoft&rsquo;s terms as our processor.
          </p>
          <p>
            Under those terms your prompts are <strong>not</strong> used to train
            Microsoft&rsquo;s models. Separately, we have a setting called{" "}
            <em>Improve the coach</em> that governs whether we may use your conversations
            to improve our own product. It is <strong>off unless you turn it on</strong>,
            and you can change it at any time in Settings.
          </p>
          <p>
            The coach is not a doctor and does not give medical advice. Messages that look
            like a health or eating-disorder crisis are answered from a fixed, written
            response and are never sent to the model at all.
          </p>
        </Section>

        <Section id="notifications" title="Notifications">
          <p>
            Push notifications are off until you allow them. When you do, your device
            registers a push token with us and we send notifications through Expo&rsquo;s
            push service, which passes them to Apple or Google to reach your phone. The
            notification text — for example that you beat a personal record — travels
            through them.
          </p>
          <p>
            You choose which kinds you receive, per category, in Settings. Account and
            security messages are the exception: those are sent regardless, because they
            are how we tell you something has happened to your account. Signing out
            removes this device&rsquo;s token.
          </p>
        </Section>

        <Section id="crash" title="Crash reports and analytics">
          <p>
            We run <strong>no advertising and no behavioural analytics</strong>. There is
            no tracking pixel, no advertising identifier, and no third-party analytics SDK
            in the app.
          </p>
          <p>
            Release builds of the mobile app send crash reports to Sentry so we can find
            and fix crashes. Those reports carry the error, the stack trace, the app
            version and your account identifier — a random id that means nothing without
            our database. They are configured to <strong>exclude</strong> request bodies,
            authentication headers, cookies, your email address and your name, so your
            training and food data does not travel with a crash.
          </p>
        </Section>

        <Section id="auth" title="Signing in with Apple or Google">
          <p>
            If you sign in with Apple or Google, they tell us a stable identifier for you
            and, if you allow it, your email address and name. We never receive your
            password, and they do not receive your CoreSync data.
          </p>
          <p>
            Apple&rsquo;s <em>Hide My Email</em> is fully supported: if you use it we only
            ever see the relay address, which is what we store.
          </p>
        </Section>

        <Section id="sharing" title="Who else sees it">
          <p>
            We do not sell your data and we do not share it for advertising. It reaches
            other companies only where they run part of the service for us:
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong>Microsoft Azure OpenAI</strong> — generates coach answers.
            </li>
            <li>
              <strong>Expo, Apple and Google</strong> — deliver push notifications.
            </li>
            <li>
              <strong>Sentry</strong> — receives crash reports, scrubbed as described
              above.
            </li>
            <li>
              <strong>Our hosting and email providers</strong> — run the servers and send
              account email.
            </li>
          </ul>
          <p>
            We would also disclose data where the law required it, and would tell you
            unless we were forbidden from doing so.
          </p>
        </Section>

        <Section id="retention" title="How long we keep it">
          <p>
            While your account is open, we keep your data so the app can show it to you —
            that is the point of a training log.
          </p>
          <p>
            When you delete your account, it is immediately deactivated and every session
            is signed out. It then sits for <strong>thirty days</strong>, during which
            signing in again cancels the deletion. After that a scheduled job{" "}
            <strong>anonymises</strong> it permanently: your email, name, date of birth,
            weigh-ins, measurements, photos, diary entries and workouts are removed.
          </p>
          <p>
            What remains afterwards is an account row with no identity attached and
            aggregate daily counts, so our own statistics about how the service was used
            stay truthful. Nothing in it can be traced back to you or restored.
          </p>
        </Section>

        <Section id="rights" title="Your rights">
          <p>
            If you are in the EEA or the UK, the GDPR gives you the right to access,
            correct, export, delete and restrict the processing of your data, and to
            object to it. You can do most of that in the app directly:
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong>Correct it</strong> — Profile and Settings.
            </li>
            <li>
              <strong>Delete it</strong> — Settings, then Delete account.
            </li>
            <li>
              <strong>Change what we may use</strong> — the AI and email switches in
              Settings.
            </li>
          </ul>
          <p>
            For anything else, including a copy of your data, write to us at the address
            below. You also have the right to complain to your national data protection
            authority.
          </p>
        </Section>

        <Section id="security" title="Security">
          <p>
            Passwords are hashed with Argon2 and never stored in a readable form. Traffic
            runs over HTTPS. Access tokens are short-lived and refresh tokens can be
            revoked, which is what signing out of all sessions does.
          </p>
          <p>
            No service is immune to a breach. If one happened and affected your data, we
            would tell you and the relevant authority as the law requires.
          </p>
        </Section>

        <Section id="children" title="Children">
          <p>
            CoreSync is not intended for children under 16, and we do not knowingly create
            accounts for them. If you believe a child has an account, contact us and we
            will remove it.
          </p>
        </Section>

        <Section id="changes" title="Changes to this policy">
          <p>
            If we change how we handle your data we will update this page and change the
            date at the top. Where a change is significant, we will tell you in the app
            rather than relying on you noticing.
          </p>
        </Section>

        <Section id="contact" title="Contact">
          <p>
            Questions about any of this, or a request about your data:{" "}
            <a
              href="mailto:privacy@coresync.app"
              className="font-medium text-accent-text underline underline-offset-4"
            >
              privacy@coresync.app
            </a>
          </p>
          <p className="text-text-muted">
            The registered company name, address and data-protection contact will be added
            here before launch.
          </p>
        </Section>
      </div>

      <footer className="mt-14 border-t border-border pt-6 text-sm text-text-muted">
        <Link href="/" className="underline underline-offset-4">
          Back to CoreSync
        </Link>
      </footer>
    </main>
  );
}
