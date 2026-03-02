import * as Sentry from '@sentry/react';

let initialized = false;

/**
 * Fetch the Sentry DSN from the backend and initialize the SDK.
 * Safe to call multiple times — only initializes once.
 */
export async function initSentry(): Promise<void> {
  if (initialized) return;

  try {
    const { settingsApi } = await import('@/lib/api');
    const { dsn } = await settingsApi.getSentryDsn();
    if (!dsn) return;

    const envLabel = process.env.NEXT_PUBLIC_ENV_LABEL || 'local';
    const sessionId = localStorage.getItem('session_id') || undefined;

    Sentry.init({
      dsn,
      environment: envLabel,
      integrations: [Sentry.browserTracingIntegration()],
      tracesSampleRate: 0.2,
      initialScope: {
        tags: { session_id: sessionId },
      },
    });

    initialized = true;
  } catch {
    // Sentry init is best-effort — don't break the app
  }
}

export { Sentry };
