'use client';

import Link from 'next/link';
import SightLabLogo from '@/components/SightLabLogo';
import { useAuth } from '@/contexts/AuthContext';

export default function MarketingShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <SightLabLogo size="sm" />
            <span className="text-lg font-semibold tracking-tight">SightLab</span>
          </Link>
          <nav className="flex items-center gap-6 text-sm">
            <Link href="/pricing" className="text-muted-foreground hover:text-foreground transition-colors">
              Pricing
            </Link>
            {isAuthenticated ? (
              <Link
                href="/generate"
                className="rounded-full bg-primary px-4 py-2 text-primary-foreground font-medium hover:opacity-90 transition-opacity"
              >
                Open app
              </Link>
            ) : (
              <>
                <Link href="/login" className="text-muted-foreground hover:text-foreground transition-colors">
                  Sign in
                </Link>
                <Link
                  href="/login?mode=signup"
                  className="rounded-full bg-primary px-4 py-2 text-primary-foreground font-medium hover:opacity-90 transition-opacity"
                >
                  Get started
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-6 py-10 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <SightLabLogo size="sm" />
            <span>© {new Date().getFullYear()} SightLab</span>
          </div>
          <nav className="flex items-center gap-6">
            <Link href="/pricing" className="hover:text-foreground transition-colors">Pricing</Link>
            <Link href="/terms" className="hover:text-foreground transition-colors">Terms</Link>
            <Link href="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
            <a href="mailto:stuart.leal23@gmail.com" className="hover:text-foreground transition-colors">Contact</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
