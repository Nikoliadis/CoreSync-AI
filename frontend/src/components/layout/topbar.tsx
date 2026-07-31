"use client";

import { Bell, Search } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/layout/logo";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn } from "@/lib/utils/cn";

export function TopBar({ title, action }: { title?: string; action?: React.ReactNode }) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border",
        // Translucent rather than solid so content scrolling underneath reads as
        // depth — the one place the design leans on blur.
        "bg-bg/80 px-4 backdrop-blur-md lg:px-6",
      )}
    >
      <div className="lg:hidden">
        <Logo compact />
      </div>

      {title && <h1 className="hidden truncate text-h2 lg:block">{title}</h1>}

      <div className="ml-auto flex items-center gap-2">
        {action}

        <button
          type="button"
          className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-text"
          aria-label="Search"
        >
          <Search className="h-5 w-5" aria-hidden />
        </button>

        <Link
          href="/notifications"
          className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-text"
          aria-label="Notifications"
        >
          <Bell className="h-5 w-5" aria-hidden />
        </Link>

        <ThemeToggle className="hidden sm:inline-flex" />
      </div>
    </header>
  );
}
