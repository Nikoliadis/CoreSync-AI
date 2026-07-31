import type { Metadata } from "next";
import { Apple } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Nutrition" };

export default function Page() {
  return (
    <ComingSoon
      title="Nutrition"
      icon={Apple}
      summary={"Food logging, macros and a daily diary. The screen is designed and routed, but there is no food database or diary API behind it yet."}
      blockedBy={"Phase 3 — food database curation, search, diary and recipe endpoints."}
      willDo={[
        "Search a curated food database and log portions in a couple of taps",
        "Calories and macro split against your targets, per day and per week",
        "Recipes you can log as a single item",
      ]}
    />
  );
}
