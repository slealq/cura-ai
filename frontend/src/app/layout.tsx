'use client';

import './globals.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { Toaster } from 'sonner';
import Sidebar from '@/components/Sidebar';
import Header from '@/components/Header';
import { ThemeProvider, useTheme } from '@/contexts/ThemeContext';

function AppShell({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();

  return (
    <>
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
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
        <title>Cura.ai</title>
        <meta name="description" content="AI-powered image tagging, description, clustering, and semantic search" />
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
            <AppShell>{children}</AppShell>
          </ThemeProvider>
        </QueryClientProvider>
      </body>
    </html>
  );
}
