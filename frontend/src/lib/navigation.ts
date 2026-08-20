import {
  Apple,
  ClipboardList,
  BarChart3,
  Bell,
  Bot,
  CalendarDays,
  Camera,
  Droplets,
  Dumbbell,
  History,
  LayoutDashboard,
  Library,
  type LucideIcon,
  Ruler,
  Settings,
  Target,
  Trophy,
  UtensilsCrossed,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /**
   * Marks a destination whose backend does not exist yet.
   *
   * Phase 3 (nutrition) was never built and progress photos were deferred in
   * Phase 4, so these routes render an honest "not yet" rather than a page wired
   * to invented data. Keeping them in the nav — visibly pending — is more useful
   * than hiding the product's shape.
   */
  pending?: boolean;
};

export type NavSection = {
  title: string;
  items: NavItem[];
};

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Train",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/workouts/active", label: "Workout Tracker", icon: Dumbbell },
      { href: "/workouts/routines", label: "Routines", icon: ClipboardList },
      { href: "/workouts", label: "History", icon: History },
      { href: "/exercises", label: "Exercise Library", icon: Library },
      { href: "/calendar", label: "Calendar", icon: CalendarDays },
    ],
  },
  {
    title: "Fuel",
    items: [
      { href: "/nutrition", label: "Nutrition", icon: Apple, pending: true },
      { href: "/nutrition/planner", label: "Meal Planner", icon: UtensilsCrossed, pending: true },
      { href: "/nutrition/water", label: "Water", icon: Droplets, pending: true },
    ],
  },
  {
    title: "Progress",
    items: [
      { href: "/progress", label: "Analytics", icon: BarChart3 },
      { href: "/progress/measurements", label: "Measurements", icon: Ruler },
      { href: "/progress/photos", label: "Photos", icon: Camera, pending: true },
      { href: "/goals", label: "Goals", icon: Target },
      { href: "/achievements", label: "Achievements", icon: Trophy },
    ],
  },
  {
    title: "Coach",
    items: [{ href: "/coach", label: "AI Coach", icon: Bot }],
  },
];

export const SECONDARY_NAV: NavItem[] = [
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Longest-prefix match, so `/workouts/active` highlights the tracker rather than
 * also lighting up `/workouts`.
 */
export function isActivePath(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  if (!pathname.startsWith(`${href}/`)) return false;

  const allHrefs = [...NAV_SECTIONS.flatMap((s) => s.items), ...SECONDARY_NAV].map((i) => i.href);
  const better = allHrefs.some(
    (candidate) =>
      candidate.length > href.length &&
      (pathname === candidate || pathname.startsWith(`${candidate}/`)),
  );
  return !better;
}
