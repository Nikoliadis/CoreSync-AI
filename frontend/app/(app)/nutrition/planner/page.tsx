import type { Metadata } from "next";
import { UtensilsCrossed } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Meal Planner" };

export default function Page() {
  return (
    <ComingSoon
      title="Meal Planner"
      icon={UtensilsCrossed}
      summary={"Plan meals ahead against your macro targets. Needs the food database that the nutrition diary is waiting on."}
      blockedBy={"Phase 3 — the same food and recipe endpoints as the diary."}
      willDo={[
        "Build a week of meals against your calorie and protein targets",
        "Copy a day or a whole week forward",
        "Turn a plan into a shopping list",
      ]}
    />
  );
}
