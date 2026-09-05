import type { Metadata } from "next";
import { UtensilsCrossed } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Meal Planner" };

export default function Page() {
  return (
    <ComingSoon
      title="Meal Planner"
      icon={UtensilsCrossed}
      summary={"Plan meals ahead against your macro targets. The diary, recipes and food search it would build on are all live, and the catalogue is no longer the obstacle it was — the hold-up now is a deliberate scoping decision rather than a missing piece."}
      blockedBy={"Product scope. Meal plans are marked out of MVP and P2 in the roadmap, so there is no schema, no endpoints and no agreed shape for a plan. Inventing one ahead of that decision would mean guessing at a data model the rest of nutrition would then have to live with."}
      willDo={[
        "Build a week of meals against your calorie and protein targets",
        "Copy a day or a whole week forward",
        "Turn a plan into a shopping list",
      ]}
    />
  );
}
