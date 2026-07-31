import type { Metadata } from "next";
import { Camera } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "Progress Photos" };

export default function Page() {
  return (
    <ComingSoon
      title="Progress Photos"
      icon={Camera}
      summary={"A private photo timeline with a comparison slider. Deferred deliberately: photos need EXIF stripping proven before any image is stored or served."}
      blockedBy={"Phase 4 — object storage, the image pipeline and the EXIF-stripping guarantee the database already enforces."}
      willDo={[
        "A timeline of your own photos, never used as decoration anywhere else",
        "Side-by-side and slider comparison between any two dates",
        "Location data stripped before the file is ever stored",
      ]}
    />
  );
}
