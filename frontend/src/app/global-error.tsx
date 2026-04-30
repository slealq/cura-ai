'use client';

import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Report to Sentry if initialized
    try {
      const Sentry = require('@sentry/react');
      if (Sentry.isInitialized?.()) {
        Sentry.captureException(error);
      }
    } catch {
      // Sentry not available — ignore
    }
    console.error('Global error:', error);
  }, [error]);

  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: 'system-ui, sans-serif', background: '#fafafa', color: '#111' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
          <div style={{ maxWidth: 400, textAlign: 'center', padding: 32, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff' }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Something went wrong</h2>
            <p style={{ fontSize: 14, color: '#666', marginBottom: 16 }}>
              {error.message || 'An unexpected error occurred.'}
            </p>
            {error.digest && (
              <p style={{ fontSize: 12, color: '#999', fontFamily: 'monospace', marginBottom: 16 }}>
                Error ID: {error.digest}
              </p>
            )}
            <button
              onClick={reset}
              style={{
                padding: '8px 16px',
                background: '#111',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              Try Again
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
