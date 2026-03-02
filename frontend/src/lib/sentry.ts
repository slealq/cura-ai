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
      integrations: [
        Sentry.browserTracingIntegration({
          enableLongAnimationFrame: true,
        }),
      ],
      // TEMPORARY: 1.0 for 2 weeks to baseline Web Vitals (LCP, CLS, INP, TTFB).
      // Reduce to 0.2 after baseline data is collected.
      tracesSampleRate: 1.0,
      initialScope: {
        tags: { session_id: sessionId },
      },
    });

    // Session Replay — deferred to Phase 3.
    //
    // Bundle cost: ~40KB gzipped. Not worth it for 1-2 users.
    //
    // When enabling, add to integrations array above:
    //   Sentry.replayIntegration({
    //     maskAllText: true,
    //     blockAllMedia: true, // user images are private
    //   })
    //
    // And add to Sentry.init options:
    //   replaysSessionSampleRate: 0.1,
    //   replaysOnErrorSampleRate: 1.0,

    initialized = true;
  } catch {
    // Sentry init is best-effort — don't break the app
  }
}

export { Sentry };
