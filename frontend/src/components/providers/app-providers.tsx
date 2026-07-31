"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { createQueryClient } from "@/lib/api/query-client";

export function AppProviders({ children }: { children: React.ReactNode }) {
  // Created in state, not at module scope: a module-level client is shared by
  // every request on the server and would leak one user's cached data into
  // another's render.
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        {children}
        <Toaster
          // Bottom on mobile (thumb reach), top-right on desktop (docs/09 §6).
          position="bottom-center"
          className="sm:!top-4 sm:!bottom-auto sm:!right-4 sm:!left-auto"
          toastOptions={{
            classNames: {
              toast:
                "!bg-surface-raised !border !border-border !text-text !rounded-lg !shadow-e3",
              description: "!text-text-secondary",
              actionButton: "!bg-accent !text-accent-ink !rounded-md",
              cancelButton: "!bg-surface-well !text-text !rounded-md",
            },
          }}
        />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
