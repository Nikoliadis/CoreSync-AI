"use client";

import { motion } from "framer-motion";
import { Bot, Dumbbell, Flame, Plus, Scale, TrendingUp } from "lucide-react";
import Link from "next/link";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ProgressRing } from "@/components/ui/progress-ring";
import { StatTile } from "@/components/ui/stat-tile";

/**
 * Lists stagger by 30ms per item, capped at 8 (docs/09 §7). The cap matters:
 * an uncapped stagger makes a long grid feel slow rather than considered.
 */
const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.03 } },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.26, ease: [0.2, 0, 0, 1] as const } },
};

export default function DashboardPage() {
  return (
    <>
      <TopBar
        title="Dashboard"
        action={
          <Button asChild size="sm" className="hidden sm:inline-flex">
            <Link href="/workouts/active">
              <Plus className="h-4 w-4" aria-hidden />
              Start workout
            </Link>
          </Button>
        }
      />

      <PageShell>
        <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-6">
          {/* --- training ---------------------------------------------------- */}
          <motion.section variants={item} aria-labelledby="training-heading">
            <h2 id="training-heading" className="sr-only">
              Training
            </h2>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatTile label="Workout streak" value="—" unit="weeks" />
              <StatTile label="This week" value="—" unit="sessions" />
              <StatTile label="Volume, 7d" value="—" unit="kg" />
              <StatTile label="Weight" value="—" unit="kg" higherIsBetter={false} />
            </div>
          </motion.section>

          {/* --- nutrition (not yet backed) ---------------------------------- */}
          <motion.section variants={item} aria-labelledby="fuel-heading">
            <h2 id="fuel-heading" className="mb-3 text-h2">
              Today&apos;s fuel
            </h2>
            <Card>
              <div className="flex flex-col items-center gap-6 py-4 sm:flex-row sm:justify-around">
                {[
                  { label: "Calories", unit: "kcal", color: "var(--color-chart-2)" },
                  { label: "Protein", unit: "g", color: "var(--color-chart-3)" },
                  { label: "Carbs", unit: "g", color: "var(--color-chart-4)" },
                  { label: "Fat", unit: "g", color: "var(--color-chart-5)" },
                  { label: "Water", unit: "ml", color: "var(--color-chart-1)" },
                ].map((macro) => (
                  <div key={macro.label} className="flex flex-col items-center gap-2">
                    <ProgressRing
                      value={0}
                      max={1}
                      label={macro.label}
                      unit={macro.unit}
                      size={92}
                      strokeWidth={8}
                      color={macro.color}
                    />
                    <span className="text-caption text-text-secondary">{macro.label}</span>
                  </div>
                ))}
              </div>
              {/* Stated rather than shown as zeros: a coach — or a user — reading
                  "0 kcal" cannot tell "ate nothing" from "logged nothing". */}
              <p className="mt-2 rounded-md bg-surface-well p-3 text-center text-caption text-text-muted">
                Nutrition tracking isn&apos;t live yet, so these are empty rather than zero.
              </p>
            </Card>
          </motion.section>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* --- today's workout ------------------------------------------ */}
            <motion.section variants={item} className="lg:col-span-2" aria-labelledby="today-heading">
              <Card>
                <CardHeader>
                  <CardTitle id="today-heading">Today&apos;s workout</CardTitle>
                </CardHeader>
                <EmptyState
                  icon={<Dumbbell className="h-8 w-8" />}
                  title="Ready when you are"
                  description="Nothing scheduled for today. Start from a routine or log freestyle."
                  action={
                    <Button asChild>
                      <Link href="/workouts/active">Start a workout</Link>
                    </Button>
                  }
                />
              </Card>
            </motion.section>

            {/* --- coach ----------------------------------------------------- */}
            <motion.section variants={item} aria-labelledby="coach-heading">
              <Card className="h-full">
                <CardHeader>
                  <CardTitle id="coach-heading">From your coach</CardTitle>
                </CardHeader>
                <EmptyState
                  icon={<Bot className="h-8 w-8" />}
                  title="No insights yet"
                  description="Log a few sessions and the coach will start spotting patterns worth telling you about."
                  action={
                    <Button variant="secondary" asChild>
                      <Link href="/coach">Ask the coach</Link>
                    </Button>
                  }
                />
              </Card>
            </motion.section>
          </div>

          {/* --- quick actions ---------------------------------------------- */}
          <motion.section variants={item} aria-labelledby="actions-heading">
            <h2 id="actions-heading" className="mb-3 text-h2">
              Quick actions
            </h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                { href: "/workouts/active", label: "Start workout", icon: Dumbbell },
                { href: "/progress/measurements", label: "Log weight", icon: Scale },
                { href: "/coach", label: "Ask the coach", icon: Bot },
                { href: "/progress", label: "See progress", icon: TrendingUp },
              ].map(({ href, label, icon: Icon }) => (
                <Link key={href} href={href}>
                  <Card variant="interactive" className="flex h-full items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-well text-accent-text">
                      <Icon className="h-5 w-5" aria-hidden />
                    </span>
                    <span className="text-body text-text">{label}</span>
                  </Card>
                </Link>
              ))}
            </div>
          </motion.section>

          {/* --- weekly ------------------------------------------------------ */}
          <motion.section variants={item} aria-labelledby="weekly-heading">
            <Card>
              <CardHeader>
                <CardTitle id="weekly-heading">Weekly progress</CardTitle>
              </CardHeader>
              <EmptyState
                icon={<Flame className="h-8 w-8" />}
                title="Not enough history yet"
                description="Once you've logged a couple of weeks, your volume and frequency trends show up here."
              />
            </Card>
          </motion.section>
        </motion.div>
      </PageShell>
    </>
  );
}
