'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

export type NotificationPreferences = { finished: boolean; failed: boolean; lowBalance: boolean };
const defaults: NotificationPreferences = { finished: true, failed: true, lowBalance: true };
const NotificationContext = createContext<{
  ready: boolean;
  preferences: NotificationPreferences;
  setPreference: (key: keyof NotificationPreferences, value: boolean) => void;
  unread: number;
  recordJob: () => void;
} | null>(null);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const storageKey = `notification-preferences:${user?.id ?? 'guest'}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [preferences, setPreferences] = useState(defaults);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    setUnread(0);
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
      setPreferences({
        finished: typeof stored.finished === 'boolean' ? stored.finished : true,
        failed: typeof stored.failed === 'boolean' ? stored.failed : true,
        lowBalance: typeof stored.lowBalance === 'boolean' ? stored.lowBalance : true,
      });
    } catch {
      setPreferences(defaults);
    }
    setLoadedKey(storageKey);
  }, [storageKey]);

  useEffect(() => {
    if (pathname === '/jobs') setUnread(0);
  }, [pathname]);

  const recordJob = useCallback(() => {
    if (pathname !== '/jobs') setUnread(count => count + 1);
  }, [pathname]);

  function setPreference(key: keyof NotificationPreferences, value: boolean) {
    const next = { ...preferences, [key]: value };
    setPreferences(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // Preferences still work for this session when storage is unavailable.
    }
  }

  return (
    <NotificationContext.Provider value={{ ready: loadedKey === storageKey, preferences, setPreference, unread, recordJob }}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) throw new Error('NotificationProvider is required');
  return context;
}
