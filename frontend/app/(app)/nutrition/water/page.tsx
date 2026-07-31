import type { Metadata } from "next";
import { Droplets } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Water" };

export default function Page() {
  return (
    <ComingSoon
      title="Water"
      icon={Droplets}
      summary={"Daily hydration against a goal. Small screen, but it still needs somewhere to store the entries."}
      blockedBy={"Phase 3 — water intake endpoints."}
      willDo={[
        "One-tap logging for your usual glass or bottle size",
        "A ring against your daily goal",
        "Streaks that count hydration alongside training",
      ]}
    />
  );
}
