import { MobileTabBar } from "@/components/layout/mobile-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { AuthGuard } from "@/features/auth/auth-guard";

/**
 * The authenticated shell.
 *
 * Client-rendered by design (docs/07 §1): making these Server Components would
 * put the user's session on the Next server and double every network hop, for a
 * faster first paint on screens users reach while already logged in.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="flex min-h-dvh">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* First tabbable element on every authenticated page — without it,
              keyboard users traverse the whole sidebar on each navigation
              (docs/09 §9). */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-ink"
          >
            Skip to content
          </a>

          <main id="main" className="flex-1 pb-20 lg:pb-0">
            {children}
          </main>
        </div>

        <MobileTabBar />
      </div>
    </AuthGuard>
  );
}
