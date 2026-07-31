"use client";

import { AnimatePresence, motion } from "framer-motion";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/layout/logo";
import { NAV_SECTIONS, SECONDARY_NAV, isActivePath, type NavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils/cn";
import { useUiStore } from "@/stores/ui-store";

function NavLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const pathname = usePathname();
  const active = isActivePath(pathname, item.href);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "group relative flex h-11 items-center gap-3 rounded-md px-3",
        "transition-colors duration-150",
        active ? "bg-surface-well text-text" : "text-text-secondary hover:bg-surface-well hover:text-text",
        collapsed && "justify-center px-0",
      )}
    >
      {/* The active marker is a shape, not just a colour change (docs/09 §9). */}
      {active && (
        <motion.span
          layoutId="sidebar-active"
          className="absolute left-0 h-6 w-0.5 rounded-full bg-accent"
          transition={{ type: "spring", stiffness: 320, damping: 30 }}
          aria-hidden
        />
      )}
      <Icon className="h-5 w-5 shrink-0" aria-hidden />
      {!collapsed && (
        <span className="flex-1 truncate text-body">{item.label}</span>
      )}
      {!collapsed && item.pending && (
        <span className="rounded-sm bg-surface-raised px-1.5 py-0.5 text-overline uppercase text-text-muted">
          Soon
        </span>
      )}
    </Link>
  );
}

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);

  return (
    <aside
      className={cn(
        "hidden shrink-0 border-r border-border bg-surface lg:flex lg:flex-col",
        "transition-[width] duration-[260ms] ease-[cubic-bezier(0.2,0,0,1)]",
        collapsed ? "w-[76px]" : "w-64",
      )}
      aria-label="Main"
    >
      <div className={cn("flex h-16 items-center px-4", collapsed && "justify-center px-0")}>
        <Logo compact={collapsed} />
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 pb-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="mb-5">
            <AnimatePresence initial={false}>
              {!collapsed && (
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="mb-1 px-3 text-overline uppercase text-text-muted"
                >
                  {section.title}
                </motion.p>
              )}
            </AnimatePresence>
            <ul className="flex flex-col gap-0.5">
              {section.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} collapsed={collapsed} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border px-3 py-3">
        <ul className="mb-1 flex flex-col gap-0.5">
          {SECONDARY_NAV.map((item) => (
            <li key={item.href}>
              <NavLink item={item} collapsed={collapsed} />
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={toggle}
          className={cn(
            "flex h-11 w-full items-center gap-3 rounded-md px-3 text-text-muted",
            "transition-colors hover:bg-surface-well hover:text-text",
            collapsed && "justify-center px-0",
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5" aria-hidden />
          ) : (
            <>
              <PanelLeftClose className="h-5 w-5" aria-hidden />
              <span className="text-body">Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
