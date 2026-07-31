"use client";

import { Bell } from "lucide-react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";

export default function NotificationsPage() {
  return (
    <>
      <TopBar title="Notifications" />
      <PageShell className="max-w-3xl">
        <Card>
          <EmptyState
            icon={<Bell className="h-8 w-8" />}
            title="Nothing here yet"
            description="Rest timers, PR celebrations and coach insights will appear here. Delivery is part of Phase 6, so nothing is sent yet."
          />
        </Card>
      </PageShell>
    </>
  );
}
