import Link from "next/link";

import { Logo } from "@/components/layout/logo";

/**
 * Centred card layout for the auth flow.
 *
 * A Server Component shell around client forms (docs/07 §1): there is no data to
 * fetch, so the page paints immediately and only the interactive form ships JS.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex h-16 items-center px-4 lg:px-8">
        <Logo />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">{children}</div>
      </main>

      <footer className="px-4 py-6 text-center text-caption text-text-muted lg:px-8">
        <Link href="/" className="hover:text-text-secondary">
          Back to home
        </Link>
      </footer>
    </div>
  );
}
