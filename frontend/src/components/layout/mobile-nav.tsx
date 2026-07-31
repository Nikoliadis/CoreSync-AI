"use client";

import { BarChart3, Bot, Dumbbell, LayoutDashboard, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/layout/logo";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { NAV_SECTIONS, SECONDARY_NAV, isActivePath } from "@/lib/navigation";
import { cn } from "@/lib/utils/cn";
import { useUiStore } from "@/stores/ui-store";

/**
 * Five destinations, thumb-height, with the primary action in the middle
 * (docs/09 §1: thumb-first).
 *
 * The rest of the tree lives behind "More" — a bottom bar that tries to hold
 * fifteen links is a bottom bar nobody can hit accurately.
 */
const TAB_BAR = [
  { href: "/dashboard", label: "Home", icon: LayoutDashboard },
  { href: "/workouts/active", label: "Train", icon: Dumbbell },
  { href: "/coach", label: "Coach", icon: Bot },
  { href: "/progress", label: "Progress", icon: BarChart3 },
];

export function MobileTabBar() {
  const pathname = usePathname();
  const open = useUiStore((s) => s.mobileNavOpen);
  const setOpen = useUiStore((s) => s.setMobileNavOpen);

  return (
    <nav
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface lg:hidden",
        // Clears the iOS home indicator.
        "pb-[env(safe-area-inset-bottom)]",
      )}
      aria-label="Primary"
    >
      <ul className="grid grid-cols-5">
        {TAB_BAR.map(({ href, label, icon: Icon }) => {
          const active = isActivePath(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-16 flex-col items-center justify-center gap-1",
                  active ? "text-accent-text" : "text-text-muted",
                )}
              >
                <Icon className="h-5 w-5" aria-hidden />
                <span className="text-overline uppercase">{label}</span>
              </Link>
            </li>
          );
        })}

        <li>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="flex h-16 w-full flex-col items-center justify-center gap-1 text-text-muted"
              >
                <Menu className="h-5 w-5" aria-hidden />
                <span className="text-overline uppercase">More</span>
              </button>
            </DialogTrigger>

            <DialogContent variant="sheet" className="max-h-[80vh]">
              <DialogTitle className="mb-4">
                <Logo />
              </DialogTitle>

              <div className="flex flex-col gap-5 pb-4">
                {NAV_SECTIONS.map((section) => (
                  <div key={section.title}>
                    <p className="mb-1 text-overline uppercase text-text-muted">{section.title}</p>
                    <ul className="flex flex-col">
                      {section.items.map((item) => {
                        const Icon = item.icon;
                        return (
                          <li key={item.href}>
                            <Link
                              href={item.href}
                              onClick={() => setOpen(false)}
                              className="flex h-12 items-center gap-3 rounded-md px-2 text-body text-text-secondary hover:bg-surface-well hover:text-text"
                            >
                              <Icon className="h-5 w-5" aria-hidden />
                              <span className="flex-1">{item.label}</span>
                              {item.pending && (
                                <span className="text-overline uppercase text-text-muted">Soon</span>
                              )}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}

                <ul className="flex flex-col border-t border-border pt-3">
                  {SECONDARY_NAV.map((item) => {
                    const Icon = item.icon;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          onClick={() => setOpen(false)}
                          className="flex h-12 items-center gap-3 rounded-md px-2 text-body text-text-secondary hover:bg-surface-well hover:text-text"
                        >
                          <Icon className="h-5 w-5" aria-hidden />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </DialogContent>
          </Dialog>
        </li>
      </ul>
    </nav>
  );
}
