import * as Sentry from '@sentry/react';

/**
 * Centralized observability helpers.
 * All functions are no-ops when Sentry is not initialized.
 */

function isReady(): boolean {
  return Sentry.getClient() !== undefined;
}

export function setUser(user: { id: string | number; email?: string } | null): void {
  if (!isReady()) return;
  if (user) {
    Sentry.setUser({ id: String(user.id), email: user.email });
  } else {
    Sentry.setUser(null);
  }
}

export function trackNavigation(from: string, to: string): void {
  if (!isReady()) return;
  Sentry.addBreadcrumb({
    category: 'navigation',
    message: `${from} -> ${to}`,
    level: 'info',
  });
}

export function trackAction(category: string, message: string, data?: Record<string, unknown>): void {
  if (!isReady()) return;
  Sentry.addBreadcrumb({
    category,
    message,
    data,
    level: 'info',
  });
}

export function trackFunnelStep(funnel: string, step: string, data?: Record<string, unknown>): void {
  if (!isReady()) return;
  Sentry.addBreadcrumb({
    category: `funnel.${funnel}`,
    message: step,
    data,
    level: 'info',
  });
  Sentry.captureMessage(`funnel:${funnel}:${step}`, {
    level: 'info',
    tags: { funnel, funnel_step: step },
    fingerprint: ['funnel', funnel, step],
    extra: data,
  });
}

export function trackSlowRequest(url: string, method: string, durationMs: number): void {
  if (!isReady()) return;
  Sentry.addBreadcrumb({
    category: 'http.slow',
    message: `${method.toUpperCase()} ${url} took ${durationMs}ms`,
    data: { url, method, durationMs },
    level: 'warning',
  });
  Sentry.captureMessage('Slow API request', {
    level: 'warning',
    tags: { slow_request: 'true' },
    fingerprint: ['slow-request', method, url],
    extra: { url, method, durationMs },
  });
}

export function captureError(error: unknown, context?: Record<string, unknown>): void {
  if (!isReady()) return;
  Sentry.captureException(error, { extra: context });
}
