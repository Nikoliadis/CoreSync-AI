import type { Metadata } from "next";
import { CalendarDays } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Calendar" };

export default function Page() {
  return (
    <ComingSoon
      title="Calendar"
      icon={CalendarDays}
      summary={"A month view of training volume and frequency. The daily aggregates behind it exist, so this one is mostly a UI build rather than a blocked one."}
      blockedBy={"Scheduling and planned-session endpoints; the heatmap data is already there."}
      willDo={[
        "A heatmap of volume per day, sequential single-hue rather than a rainbow",
        "Jump straight from a day to that session",
        "Plan sessions ahead and see them alongside what you actually did",
      ]}
    />
  );
}
