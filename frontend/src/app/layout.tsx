'use client';

import './globals.css';
import { QueryCache, QueryClient, QueryClientProvider, MutationCache } from '@tanstack/react-query';
import { useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AxiosError } from 'axios';
import { Toaster, toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import Header from '@/components/Header';
import { ThemeProvider, useTheme } from '@/contexts/ThemeContext';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { UploadProvider } from '@/contexts/UploadContext';
import { useJobNotifications } from '@/hooks/useJobNotifications';
import { useEffect, useRef } from 'react';
import { initSentry } from '@/lib/sentry';
import { setUser, trackNavigation, captureError } from '@/lib/observability';

function SentryInit() {
  const didInit = useRef(false);
  useEffect(() => {
    if (!didInit.current) {
      didInit.current = true;
      initSentry();
    }
  }, []);
  return null;
}

function SentryUserSync() {
  const { user } = useAuth();
  const pathname = usePathname();
  const prevPathRef = useRef(pathname);

  useEffect(() => {
    if (user) {
      setUser({ id: user.id, email: user.email });
    } else {
      setUser(null);
    }
  }, [user]);

  useEffect(() => {
    const prev = prevPathRef.current;
    if (prev !== pathname) {
      trackNavigation(prev, pathname);
      prevPathRef.current = pathname;
    }
  }, [pathname]);

  return null;
}

function AppShell({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();
  useJobNotifications();

  return (
    <>
      <SentryUserSync />
      <div className="flex h-screen">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Header />
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </div>
      <Toaster position="bottom-right" richColors theme={resolvedTheme} />
    </>
  );
}

// Marketing/public pages render without the app shell and never redirect to login
const PUBLIC_ROUTES = ['/', '/pricing', '/terms', '/privacy', '/login'];

function AuthGate({ children }: { children: React.ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const { resolvedTheme } = useTheme();

  const normalizedPath = pathname !== '/' ? pathname.replace(/\/+$/, '') : '/';
  const isPublic = PUBLIC_ROUTES.includes(normalizedPath);

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isPublic) {
      router.replace('/login');
    }
  }, [isLoading, isAuthenticated, isPublic, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (isPublic) {
    return (
      <>
        {children}
        <Toaster position="bottom-right" richColors theme={resolvedTheme} />
      </>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return <AppShell>{children}</AppShell>;
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            const axiosErr = error as AxiosError;
            const status = axiosErr.response?.status;
            // Skip 401s — handled by Axios interceptor refresh logic
            if (status === 401) return;
            // Skip background refetch failures when cached data exists (stale-while-revalidate)
            if (query.state.data !== undefined) return;
            // Toast user-facing error
            const message = error.message || 'Something went wrong';
            toast.error(message);
            // Report 5xx errors to Sentry
            if (status && status >= 500) {
              captureError(error, { queryKey: query.queryKey, status });
            }
          },
        }),
        mutationCache: new MutationCache({
          onError: (error) => {
            // Don't toast — mutations have per-component onError toasts.
            // Just report 5xx to Sentry.
            const axiosErr = error as AxiosError;
            const status = axiosErr.response?.status;
            if (status && status >= 500) {
              captureError(error, { status });
            }
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 30000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <title>SightLab</title>
        <meta name="description" content="SightLab — AI-powered image intelligence, tagging, and generation" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme') || 'light';
                  var dark = false;
                  if (theme === 'dark') {
                    dark = true;
                  } else if (theme === 'auto') {
                    var tz = localStorage.getItem('timezone') || Intl.DateTimeFormat().resolvedOptions().timeZone;
                    var hour = parseInt(new Intl.DateTimeFormat('en-US', { hour: 'numeric', hour12: false, timeZone: tz }).format(new Date()), 10);
                    dark = hour < 7 || hour >= 19;
                  }
                  if (dark) document.documentElement.classList.add('dark');
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="min-h-screen bg-background">
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <AuthProvider>
              <UploadProvider>
                <SentryInit />
                <AuthGate>{children}</AuthGate>
              </UploadProvider>
            </AuthProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </body>
    </html>
  );
}
