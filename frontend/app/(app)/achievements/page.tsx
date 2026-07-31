import type { Metadata } from "next";
import { Trophy } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Achievements" };

export default function Page() {
  return (
    <ComingSoon
      title="Achievements"
      icon={Trophy}
      summary={"Milestones worth marking — first PR, first month, consistency runs. The underlying records exist; the awarding rules do not."}
      blockedBy={"Phase 6 — achievement definitions and the awarding job."}
      willDo={[
        "Milestones derived from records you already have",
        "Never punitive: nothing here counts what you missed",
        "Shareable without exposing your data",
      ]}
    />
  );
}
