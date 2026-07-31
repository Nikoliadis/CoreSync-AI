"use client";

import { Target } from "lucide-react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";

export default function GoalsPage() {
  return (
    <>
      <TopBar title="Goals" />
      <PageShell className="max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle>Your goal</CardTitle>
          </CardHeader>
          <EmptyState
            icon={<Target className="h-8 w-8" />}
            title="No goal set"
            description="A target weight and a weekly rate let the coach tell you whether what you are doing is working."
          />
        </Card>
      </PageShell>
    </>
  );
}
