'use client';

import { useNotifications, type NotificationPreferences } from '@/contexts/NotificationContext';

const options: { key: keyof NotificationPreferences; title: string; description: string }[] = [
  { key: 'finished', title: 'A job finishes', description: 'In the app' },
  { key: 'failed', title: 'A job fails', description: 'In the app' },
  { key: 'lowBalance', title: 'Sparks run low', description: 'Below 200 sparks' },
];

export default function NotificationsPage() {
  const { preferences, setPreference } = useNotifications();

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 hidden text-2xl font-semibold md:block">Notifications</h1>
      <h2 className="mb-2 text-sm text-muted-foreground">Tell me when</h2>
      {options.map(option => (
        <div key={option.key} className="flex items-center gap-4 border-b border-border py-4">
          <div className="flex-1">
            <p className="font-medium">{option.title}</p>
            <p className="text-sm text-muted-foreground">{option.description}</p>
          </div>
          <button
            role="switch"
            aria-checked={preferences[option.key]}
            aria-label={option.title}
            onClick={() => setPreference(option.key, !preferences[option.key])}
            className="flex min-h-10 min-w-12 items-center justify-center"
          >
            <span className={`flex h-6 w-11 items-center rounded-full p-1 ${preferences[option.key] ? 'bg-primary' : 'bg-muted'}`}>
              <span className={`h-4 w-4 rounded-full bg-background transition-transform ${preferences[option.key] ? 'translate-x-5' : ''}`} />
            </span>
          </button>
        </div>
      ))}
      <div className="flex items-center gap-4 border-b border-border py-4">
        <div className="flex-1">
          <p className="font-medium">Send to this phone when the app is closed</p>
          <p className="text-sm text-muted-foreground">Coming later</p>
        </div>
        <button role="switch" aria-label="Closed-app notifications, coming later" aria-checked={false} disabled className="min-h-10 min-w-12 text-sm text-muted-foreground">Off</button>
      </div>
    </div>
  );
}
