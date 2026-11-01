'use client';

import './globals.css';
import { QueryCache, QueryClient, QueryClientProvider, MutationCache } from '@tanstack/react-query';
import { useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AxiosError } from 'axios';
import { Toaster, toast } from 'sonner';
import MobileStatus from '@/components/MobileStatus';
import Link from 'next/link';
import MobileNavigation from '@/components/MobileNavigation';
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
  const pathname = usePathname();
  const tool = ['/edit', '/generate', '/vision', '/models', '/search'].includes(pathname);
  const [modelTitle, setModelTitle] = useState('');
  const [editTitle, setEditTitle] = useState('Edit');
  useEffect(() => {
    const update = (event: Event) => setEditTitle((event as CustomEvent<string>).detail);
    const updateModel = (event: Event) => setModelTitle((event as CustomEvent<string>).detail);
    window.addEventListener('mobile-model-title', updateModel);
    window.addEventListener('mobile-edit-title', update);
    return () => { window.removeEventListener('mobile-edit-title', update); window.removeEventListener('mobile-model-title', updateModel); };
  }, []);
  // Every page under a tab goes back to that tab's hub.
  const parent = ['/collection', '/studio', '/account'].includes(pathname) ? null
    : ['/edit', '/generate', '/vision', '/models'].some(path => pathname.startsWith(path)) ? '/studio'
    : ['/billing', '/jobs', '/notifications', '/settings', '/admin', '/debug'].some(path => pathname.startsWith(path)) ? '/account'
    : '/collection';
  const title = ({ '/images': 'All images', '/collection': 'Collection', '/studio': 'Studio', '/account': 'Account', '/edit': 'Edit', '/generate': 'Create', '/vision': 'Vision', '/search': 'Search' } as Record<string, string>)[pathname] ?? pathname.split('/')[1].replace(/^./, c => c.toUpperCase());

  return (
    <>
      <SentryUserSync />
      <div className={`app-shell flex h-screen ${tool ? 'mobile-tool' : ''}`}>
        <Sidebar />
        <MobileNavigation />
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Header />
          <div className="mobile-topbar flex shrink-0 items-center gap-2 border-b border-border px-3 md:hidden">
            {parent && (pathname === '/models' && modelTitle ? <button className="min-h-10 pr-1 text-sm" onClick={() => window.dispatchEvent(new Event('mobile-model-back'))}>Back</button> : <Link href={parent} className="flex min-h-10 items-center pr-1 text-sm">Back</Link>)}
            <h1 className="text-lg font-semibold">{pathname === '/edit' ? <button className="min-h-10 text-left" onClick={() => window.dispatchEvent(new Event('mobile-edit-jobs'))}>{editTitle} ▾</button> : pathname === '/models' ? modelTitle || 'My models' : title}</h1>
            <MobileStatus />
          </div>
          <main className="app-main flex-1 overflow-auto px-5 py-5">{children}</main>
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
    if (!isLoading && normalizedPath === '/' && window.matchMedia('(max-width: 767px)').matches) {
      router.replace(isAuthenticated ? '/collection' : '/login');
      return;
    }
    if (!isLoading && !isAuthenticated && !isPublic) {
      router.replace('/login');
    }
  }, [isLoading, isAuthenticated, isPublic, normalizedPath, router]);

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
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
        <meta name="theme-color" content="#141415" media="(prefers-color-scheme: dark)" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-title" content="SightLab" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <meta name="description" content="SightLab — AI-powered image intelligence, tagging, and generation" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap"
        />
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
