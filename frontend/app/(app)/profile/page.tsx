"use client";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useCurrentUser } from "@/features/auth/hooks";

export default function ProfilePage() {
  const user = useCurrentUser();

  return (
    <>
      <TopBar title="Profile" />
      <PageShell className="max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle>Your profile</CardTitle>
          </CardHeader>
          <div className="flex items-center gap-4">
            <span
              className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-well text-h2 text-text-secondary"
              aria-hidden
            >
              {user?.email?.[0]?.toUpperCase() ?? "?"}
            </span>
            <div className="min-w-0">
              <p className="truncate text-h3 text-text">{user?.email ?? "—"}</p>
              <p className="text-caption capitalize text-text-muted">
                {user?.tier ?? "free"} plan
              </p>
            </div>
          </div>
        </Card>
      </PageShell>
    </>
  );
}
