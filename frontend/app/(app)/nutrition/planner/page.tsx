import type { Metadata } from "next";
import { UtensilsCrossed } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Meal Planner" };

export default function Page() {
  return (
    <ComingSoon
      title="Meal Planner"
      icon={UtensilsCrossed}
      summary={"Plan meals ahead against your macro targets. The diary, recipes and food search it would build on are all live now — what it still needs is a food catalogue big enough to plan a week from."}
      blockedBy={"A larger food database. Planning seven days from a few dozen curated foods would produce the same three dinners on repeat."}
      willDo={[
        "Build a week of meals against your calorie and protein targets",
        "Copy a day or a whole week forward",
        "Turn a plan into a shopping list",
      ]}
    />
  );
}
