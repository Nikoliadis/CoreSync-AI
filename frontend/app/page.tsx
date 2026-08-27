import { ArrowRight, Bot, LineChart, ShieldCheck, Timer } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

// Static by default — this page has no user data, so it should be SEO-friendly
// and instant (docs/07 §1).
export const metadata: Metadata = {
  title: "CoreSync — Train with intent",
  description:
    "Log your training, watch the trend, and get coaching grounded in your own numbers — not generic advice.",
};

const FEATURES = [
  {
    icon: Timer,
    title: "Logging that keeps up",
    body: "Sets land in one tap with a rest timer that survives a locked screen. Works offline and syncs when you're back.",
  },
  {
    icon: LineChart,
    title: "The trend, not the noise",
    body: "Smoothed weight trend and estimated 1RM per lift, so a heavy meal or a dehydrated morning doesn't read as progress.",
  },
  {
    icon: Bot,
    title: "A coach that read your data",
    body: "Answers cite your actual sessions. It says what stalled and for how long, instead of generic advice you could search for.",
  },
  {
    icon: ShieldCheck,
    title: "Safety built in, not prompted",
    body: "Calorie floors and medical boundaries are enforced in code before and after the model runs — not asked for politely in a prompt.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 lg:px-8">
        <Logo />
        <nav className="flex items-center gap-2">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/login">Log in</Link>
          </Button>
          <Button size="sm" asChild>
            <Link href="/register">Get started</Link>
          </Button>
        </nav>
      </header>

      <main>
        {/* --- hero --------------------------------------------------------- */}
        <section className="mx-auto w-full max-w-6xl px-4 pb-16 pt-12 lg:px-8 lg:pt-24">
          <div className="max-w-3xl">
            <p className="text-overline uppercase text-accent-text">Strength · Nutrition · AI coaching</p>
            <h1 className="mt-3 text-display text-text lg:text-[3.5rem] lg:leading-[1.05]">
              Train with intent.
              <br />
              <span className="text-text-secondary">Let the numbers do the arguing.</span>
            </h1>
            <p className="mt-5 max-w-xl text-body-lg text-text-secondary">
              CoreSync tracks what you actually lifted, smooths out the day-to-day noise, and gives
              you a coach that answers from your own history.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Button size="lg" asChild>
                <Link href="/register">
                  Start free
                  <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
              </Button>
              <Button size="lg" variant="secondary" asChild>
                <Link href="/login">I already have an account</Link>
              </Button>
            </div>
          </div>
        </section>

        {/* --- features ----------------------------------------------------- */}
        <section className="mx-auto w-full max-w-6xl px-4 py-16 lg:px-8" aria-labelledby="features">
          <h2 id="features" className="text-h1 text-text">
            Built around the set you&apos;re about to do
          </h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <Card key={title} padding="lg">
                <span
                  className="mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-surface-well text-accent-text"
                  aria-hidden
                >
                  <Icon className="h-5 w-5" />
                </span>
                <h3 className="text-h3 text-text">{title}</h3>
                <p className="mt-2 text-body text-text-secondary">{body}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* --- close -------------------------------------------------------- */}
        <section className="mx-auto w-full max-w-6xl px-4 pb-24 lg:px-8">
          <Card variant="raised" padding="lg" className="text-center">
            <h2 className="text-h1 text-text">Your first session is the hardest</h2>
            <p className="mx-auto mt-2 max-w-md text-body text-text-secondary">
              After that it&apos;s just showing up — and we&apos;ll keep the record.
            </p>
            <Button size="lg" className="mt-6" asChild>
              <Link href="/register">Create your account</Link>
            </Button>
          </Card>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-8 text-caption text-text-muted lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <p>© {new Date().getFullYear()} CoreSync</p>
          <Link href="/privacy" className="underline underline-offset-4 hover:text-text">
            Privacy policy
          </Link>
          {/* The product-wide rule, stated where anyone can see it (docs/09 §10). */}
          <p>Coaching guidance, not medical advice.</p>
        </div>
      </footer>
    </div>
  );
}
