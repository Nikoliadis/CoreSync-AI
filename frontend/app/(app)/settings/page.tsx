"use client";

import { LogOut } from "lucide-react";

import { PageShell } from "@/components/layout/page-header";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthActions, useCurrentUser } from "@/features/auth/hooks";

export default function SettingsPage() {
  const user = useCurrentUser();
  const { logout } = useAuthActions();

  return (
    <>
      <TopBar title="Settings" />

      <PageShell className="max-w-3xl">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Account</CardTitle>
            </CardHeader>
            <dl className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-body text-text-secondary">Email</dt>
                <dd className="truncate text-body text-text">{user?.email ?? "—"}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-body text-text-secondary">Plan</dt>
                <dd className="text-body capitalize text-text">{user?.tier ?? "—"}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-body text-text-secondary">Timezone</dt>
                <dd className="text-body text-text">{user?.timezone ?? "—"}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-body text-text-secondary">Email verified</dt>
                <dd className="text-body text-text">{user?.emailVerified ? "Yes" : "Not yet"}</dd>
              </div>
            </dl>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Appearance</CardTitle>
            </CardHeader>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-body text-text">Theme</p>
                <p className="text-caption text-text-muted">
                  Dark is the default. System follows your device.
                </p>
              </div>
              <ThemeToggle />
            </div>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Session</CardTitle>
            </CardHeader>
            <Button variant="secondary" onClick={() => void logout()}>
              <LogOut className="h-4 w-4" aria-hidden />
              Log out
            </Button>
          </Card>
        </div>
      </PageShell>
    </>
  );
}
