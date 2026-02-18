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
  CreditCard,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { cn, formatNumber } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import { billingApi } from '@/lib/api';

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
  { name: 'Images', href: '/images', icon: FolderOpen },
  { name: 'Clusters', href: '/clusters', icon: LayoutGrid },
  { name: 'Models', href: '/models', icon: Box },
  { name: 'Vision', href: '/vision', icon: Eye },
  { name: 'Generate', href: '/generate', icon: Sparkles },
  { name: 'Edit', href: '/edit', icon: Pencil },
  { name: 'Jobs', href: '/jobs', icon: Activity },
  { name: 'Billing', href: '/billing', icon: CreditCard },
  { name: 'Debug', href: '/debug', icon: Bug },
  { name: 'Settings', href: '/settings', icon: Settings },
];

function getSparkTier(balance: number) {
  if (balance <= 0) return { label: 'Empty', color: 'text-red-500', bg: 'bg-red-500', glow: 'shadow-red-500/40', barBg: 'bg-red-500/15', pct: 0 };
  if (balance < 50) return { label: 'Low', color: 'text-orange-400', bg: 'bg-orange-400', glow: 'shadow-orange-400/40', barBg: 'bg-orange-400/15', pct: Math.max(5, (balance / 50) * 15) };
  if (balance < 500) return { label: 'Warm', color: 'text-amber-400', bg: 'bg-amber-400', glow: 'shadow-amber-400/30', barBg: 'bg-amber-400/15', pct: 15 + ((balance - 50) / 450) * 25 };
  if (balance < 2000) return { label: 'Charged', color: 'text-yellow-400', bg: 'bg-yellow-400', glow: 'shadow-yellow-400/30', barBg: 'bg-yellow-400/10', pct: 40 + ((balance - 500) / 1500) * 25 };
  if (balance < 5000) return { label: 'Supercharged', color: 'text-emerald-400', bg: 'bg-emerald-400', glow: 'shadow-emerald-400/30', barBg: 'bg-emerald-400/10', pct: 65 + ((balance - 2000) / 3000) * 20 };
  return { label: 'Overloaded', color: 'text-cyan-400', bg: 'bg-cyan-400', glow: 'shadow-cyan-400/40', barBg: 'bg-cyan-400/10', pct: Math.min(100, 85 + ((balance - 5000) / 10000) * 15) };
}

function SparkBalance({ balance }: { balance: number }) {
  const tier = getSparkTier(balance);
  return (
    <div className={cn(
      'rounded-lg border border-border px-3 py-2.5 transition-all',
      'hover:border-border/80 hover:bg-muted/30',
      tier.barBg,
    )}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <Zap className={cn('h-3.5 w-3.5', tier.color, balance > 0 && 'drop-shadow-sm')} />
          <span className={cn('text-[11px] font-semibold uppercase tracking-wider', tier.color)}>
            {tier.label}
          </span>
        </div>
        <span className="text-xs text-muted-foreground font-medium">
          sparks
        </span>
      </div>
      <div className="text-lg font-bold tracking-tight leading-none mb-1.5">
        {formatNumber(balance)}
      </div>
      <div className="h-1 rounded-full bg-muted/50 overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-700 ease-out', tier.bg)}
          style={{ width: `${tier.pct}%` }}
        />
      </div>
    </div>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const { data: balanceData } = useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: billingApi.getBalance,
    refetchInterval: 30000,
    enabled: !!user,
  });

  const isAdmin = user?.role === 'admin';

  // Build navigation with conditional admin item
  const navItems = [
    ...navigation,
    ...(isAdmin ? [{ name: 'Admin', href: '/admin', icon: ShieldCheck }] : []),
  ];

  return (
    <aside className="w-64 bg-card border-r border-border flex flex-col">
      <div className="p-6 border-b border-border">
        <Link href="/generate" className="flex items-center gap-2">
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

      {balanceData && (
        <Link href="/billing" className="block mx-4 mt-4 group">
          <SparkBalance balance={balanceData.balance} />
        </Link>
      )}

      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => {
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
          <div className="space-y-2">
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
          </div>
        )}
      </div>
    </aside>
  );
}
