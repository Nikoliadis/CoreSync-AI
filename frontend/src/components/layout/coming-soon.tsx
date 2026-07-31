import { Construction, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * The honest placeholder for a screen whose backend does not exist yet.
 *
 * It states plainly what is missing and why, rather than showing a polished UI
 * driven by invented numbers. Fake data in a fitness product is worse than an
 * empty screen: a calorie total nobody logged is indistinguishable from one they
 * did, and the whole point of the product is that the numbers are real.
 */
export function ComingSoon({
  title,
  icon: Icon = Construction,
  summary,
  blockedBy,
  willDo,
}: {
  title: string;
  icon?: LucideIcon;
  summary: string;
  blockedBy: string;
  willDo: string[];
}) {
  return (
    <>
      <TopBar title={title} />
      <PageShell>
        <div className="mx-auto max-w-2xl">
          <Card padding="lg" className="text-center">
            <div
              className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-surface-well text-text-muted"
              aria-hidden
            >
              <Icon className="h-6 w-6" />
            </div>

            <h2 className="text-h2 text-text">{title} isn&apos;t live yet</h2>
            <p className="mx-auto mt-2 max-w-md text-body text-text-secondary">{summary}</p>

            <div className="mt-6 rounded-md border border-border bg-surface-well p-4 text-left">
              <p className="text-overline uppercase text-text-muted">Waiting on</p>
              <p className="mt-1 text-body text-text-secondary">{blockedBy}</p>
            </div>

            <div className="mt-4 rounded-md border border-border p-4 text-left">
              <p className="text-overline uppercase text-text-muted">What it will do</p>
              <ul className="mt-2 flex flex-col gap-1.5">
                {willDo.map((line) => (
                  <li key={line} className="flex gap-2 text-body text-text-secondary">
                    <span className="text-accent-text" aria-hidden>
                      —
                    </span>
                    {line}
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
              <Button asChild>
                <Link href="/dashboard">Back to dashboard</Link>
              </Button>
              <Button variant="secondary" asChild>
                <Link href="/workouts/active">Start a workout</Link>
              </Button>
            </div>
          </Card>
        </div>
      </PageShell>
    </>
  );
}
