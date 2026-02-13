'use client';

import { createContext, useContext, useEffect, useState, useCallback } from 'react';

type Theme = 'light' | 'dark' | 'auto';
type ResolvedTheme = 'light' | 'dark';

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
  timezone: string;
  setTimezone: (tz: string) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function getSystemTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

function resolveAutoTheme(timezone: string): ResolvedTheme {
  try {
    const now = new Date();
    const formatter = new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      hour12: false,
      timeZone: timezone,
    });
    const hour = parseInt(formatter.format(now), 10);
    return hour >= 7 && hour < 19 ? 'light' : 'dark';
  } catch {
    return 'light';
  }
}

function applyThemeClass(resolved: ResolvedTheme) {
  const root = document.documentElement;
  if (resolved === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>('light');
  const [timezone, setTimezoneState] = useState<string>(getSystemTimezone());
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>('light');
  const [mounted, setMounted] = useState(false);

  // Initialize from localStorage on mount
  useEffect(() => {
    const storedTheme = localStorage.getItem('theme') as Theme | null;
    const storedTz = localStorage.getItem('timezone');

    const t = storedTheme || 'light';
    const tz = storedTz || getSystemTimezone();

    setThemeState(t);
    setTimezoneState(tz);

    const resolved = t === 'auto' ? resolveAutoTheme(tz) : t;
    setResolvedTheme(resolved);
    applyThemeClass(resolved);
    setMounted(true);
  }, []);

  // Auto mode: recheck every 60s
  useEffect(() => {
    if (theme !== 'auto') return;

    const check = () => {
      const resolved = resolveAutoTheme(timezone);
      setResolvedTheme(resolved);
      applyThemeClass(resolved);
    };

    check();
    const interval = setInterval(check, 60_000);
    return () => clearInterval(interval);
  }, [theme, timezone]);

  const setTheme = useCallback(
    (newTheme: Theme) => {
      setThemeState(newTheme);
      localStorage.setItem('theme', newTheme);

      const resolved = newTheme === 'auto' ? resolveAutoTheme(timezone) : newTheme;
      setResolvedTheme(resolved);
      applyThemeClass(resolved);
    },
    [timezone]
  );

  const setTimezone = useCallback(
    (tz: string) => {
      setTimezoneState(tz);
      localStorage.setItem('timezone', tz);

      if (theme === 'auto') {
        const resolved = resolveAutoTheme(tz);
        setResolvedTheme(resolved);
        applyThemeClass(resolved);
      }
    },
    [theme]
  );

  // Prevent flash: don't render children until mounted
  if (!mounted) {
    return null;
  }

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme, timezone, setTimezone }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
