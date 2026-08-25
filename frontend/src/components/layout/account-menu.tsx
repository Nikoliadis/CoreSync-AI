"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LogOut, Settings, User } from "lucide-react";
import Link from "next/link";

import { useAuthActions, useCurrentUser } from "@/features/auth/hooks";
import { cn } from "@/lib/utils/cn";

/**
 * Who you are signed in as, and the way out.
 *
 * Logging out already existed, buried on the settings page. That is two navigations to
 * find, and — more to the point — nothing anywhere in the shell showed *which account*
 * was signed in. On a product where a stale session silently logs a workout to the wrong
 * account, that is worth a permanent affordance rather than a page.
 *
 * Identity is the email address, because it is the only thing the client actually holds:
 * `AuthenticatedUser` carries no display name and there is no profile fetch on the web.
 * Inventing a nicer label would mean a request on every page load for a decoration.
 */
export function AccountMenu() {
  const user = useCurrentUser();
  const { logout } = useAuthActions();

  if (!user) return null;

  const initial = user.email.trim().charAt(0).toUpperCase() || "?";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          // The label carries the address. Without it a screen reader announces a
          // single letter, which tells nobody anything.
          aria-label={`Account: ${user.email}`}
          className={cn(
            "flex h-11 w-11 items-center justify-center rounded-full",
            "bg-surface-well text-body font-semibold text-text",
            "transition-colors hover:bg-border focus-visible:outline-2",
            "focus-visible:outline-offset-2 focus-visible:outline-accent",
          )}
        >
          {initial}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            "z-50 min-w-56 rounded-lg border border-border bg-surface-raised p-1",
            "shadow-[var(--shadow-3)]",
            // Radix sets these data attributes during the open and close transitions.
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
          )}
        >
          <div className="px-3 py-2">
            <p className="text-caption text-text-muted">Signed in as</p>
            {/* Truncated rather than wrapped: a long address must not resize the menu. */}
            <p className="truncate text-body text-text" title={user.email}>
              {user.email}
            </p>
            {!user.emailVerified && (
              // Surfaced here because it is the one place the user always has access to,
              // and an unverified account silently behaves differently.
              <p className="mt-1 text-caption text-warning">Email not verified</p>
            )}
          </div>

          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <MenuLink href="/profile" icon={<User className="h-4 w-4" aria-hidden />}>
            Profile
          </MenuLink>
          <MenuLink href="/settings" icon={<Settings className="h-4 w-4" aria-hidden />}>
            Settings
          </MenuLink>

          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <DropdownMenu.Item
            onSelect={() => void logout()}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-md px-3 py-2",
              "text-body text-critical outline-none",
              "data-[highlighted]:bg-surface-well",
            )}
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Log out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function MenuLink({
  href,
  icon,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenu.Item asChild>
      <Link
        href={href}
        className={cn(
          "flex cursor-pointer items-center gap-2 rounded-md px-3 py-2",
          "text-body text-text outline-none",
          "data-[highlighted]:bg-surface-well",
        )}
      >
        {icon}
        {children}
      </Link>
    </DropdownMenu.Item>
  );
}
