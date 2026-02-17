'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutGrid,
  FolderOpen,
  Folder,
  Settings,
  Activity,
  Upload,
  Bug,
  Sparkles,
  Pencil,
  Eye,
  Box,
  LogOut,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

const ENV_LABEL = process.env.NEXT_PUBLIC_ENV_LABEL || 'local';

const ENV_BADGE: Record<string, { label: string; color: string } | null> = {
  local: { label: 'Local', color: 'blue' },
  'cloud-native': { label: 'Cloud Native', color: 'emerald' },
  'cloud-docker': { label: 'Cloud Docker', color: 'teal' },
  dev: { label: 'DEV', color: 'purple' },
  prod: null,
};

const BADGE_COLORS: Record<string, { bg: string; text: string; border: string; dot: string; pulse: boolean }> = {
  blue: { bg: 'bg-blue-500/15', text: 'text-blue-500', border: 'border-blue-500/25', dot: 'bg-blue-500', pulse: false },
  emerald: { bg: 'bg-emerald-500/15', text: 'text-emerald-500', border: 'border-emerald-500/25', dot: 'bg-emerald-500', pulse: true },
  teal: { bg: 'bg-teal-500/15', text: 'text-teal-500', border: 'border-teal-500/25', dot: 'bg-teal-500', pulse: true },
  purple: { bg: 'bg-purple-500/15', text: 'text-purple-500', border: 'border-purple-500/25', dot: 'bg-purple-500', pulse: true },
};

const navigation = [
  { name: 'Upload', href: '/upload', icon: Upload },
  { name: 'Folders', href: '/images', icon: FolderOpen },
  { name: 'Clusters', href: '/', icon: LayoutGrid },
  { name: 'Models', href: '/models', icon: Box },
  { name: 'Vision', href: '/vision', icon: Eye },
  { name: 'Generate', href: '/generate', icon: Sparkles },
  { name: 'Edit', href: '/edit', icon: Pencil },
  { name: 'Jobs', href: '/jobs', icon: Activity },
  { name: 'Debug', href: '/debug', icon: Bug },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="w-64 bg-card border-r border-border flex flex-col">
      <div className="p-6 border-b border-border">
        <Link href="/" className="flex items-center gap-2">
          <Folder className="h-8 w-8 text-primary" />
          <div>
            <h1 className="font-semibold text-lg">Cura.ai</h1>
            <p className="text-xs text-muted-foreground">
              Image Intelligence
            </p>
            {ENV_BADGE[ENV_LABEL] && (() => {
              const colors = BADGE_COLORS[ENV_BADGE[ENV_LABEL]!.color];
              return (
                <span className={cn(
                  'inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider border',
                  colors.bg, colors.text, colors.border,
                )}>
                  <span className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    colors.dot, colors.pulse && 'animate-pulse',
                  )} />
                  {ENV_BADGE[ENV_LABEL]!.label}
                </span>
              );
            })()}
          </div>
        </Link>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {navigation.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href));

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-border">
        {user && (
          <div className="flex items-center justify-between">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">
                {user.display_name || user.email}
              </p>
              {user.display_name && (
                <p className="text-xs text-muted-foreground truncate">{user.email}</p>
              )}
            </div>
            <button
              onClick={logout}
              className="ml-2 p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
