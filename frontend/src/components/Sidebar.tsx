'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  Box,
  Bug,
  ChevronsLeft,
  ChevronsRight,
  CreditCard,
  Eye,
  FolderOpen,
  Image as ImageIcon,
  LayoutGrid,
  LogOut,
  Pencil,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import SightLabLogo from '@/components/SightLabLogo';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import { clustersApi, foldersApi } from '@/lib/api';

const ENV_LABEL = process.env.NEXT_PUBLIC_ENV_LABEL || 'local';

const ENV_BADGE: Record<string, { label: string; className: string } | null> = {
  local: { label: 'Local', className: 'bg-blue-500/10 text-blue-600 dark:text-blue-400' },
  'cloud-native': { label: 'Native', className: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  'cloud-docker': { label: 'Docker', className: 'bg-teal-500/10 text-teal-600 dark:text-teal-400' },
  dev: { label: 'Dev', className: 'bg-purple-500/10 text-purple-600 dark:text-purple-400' },
  prod: null,
};

const SIDEBAR_FOLDER_LIMIT = 8;
const SIDEBAR_CLUSTER_LIMIT = 6;
const COLLAPSED_KEY = 'sidebar-collapsed';

function NavItem({
  href,
  icon: Icon,
  label,
  count,
  active,
  collapsed,
}: {
  href: string;
  icon: LucideIcon;
  label: string;
  count?: number;
  active: boolean;
  collapsed: boolean;
}) {
  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] font-medium transition-colors',
        collapsed && 'justify-center px-0',
        active
          ? 'bg-background text-foreground shadow-[0_0_0_1px_hsl(var(--border)),0_1px_2px_rgb(0_0_0/0.04)] dark:bg-accent dark:shadow-none'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
      {!collapsed && count != null && (
        <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">{count}</span>
      )}
    </Link>
  );
}

function GroupLabel({ children, href, collapsed }: { children: string; href?: string; collapsed: boolean }) {
  if (collapsed) return <div className="mx-3 my-2 border-t border-border" />;
  const cls = 'block px-2 pb-1 pt-3 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-foreground';
  return href ? (
    <Link href={href} className={cn(cls, 'hover:text-foreground')}>{children}</Link>
  ) : (
    <div className={cls}>{children}</div>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSED_KEY) === '1');
    } catch {
      // localStorage unavailable — keep expanded
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, prev ? '0' : '1');
      } catch {
        // ignore
      }
      return !prev;
    });
  };

  // Shares the ['folders', ...] prefix so folder mutations invalidate it too
  const { data: folderData } = useQuery({
    queryKey: ['folders', 'sidebar'],
    queryFn: () => foldersApi.list({ limit: 50 }),
    enabled: !!user,
  });

  const { data: clusterData } = useQuery({
    queryKey: ['clusters', 'sidebar'],
    queryFn: () => clustersApi.list({ limit: 50 }),
    enabled: !!user,
  });

  // Hide folders that are being deleted (same sessionStorage contract as the Images page)
  const folders = useMemo(() => {
    const items = folderData?.items ?? [];
    try {
      const raw = sessionStorage.getItem('deleting-folders');
      if (!raw) return items;
      const deleting = new Set<number>(JSON.parse(raw) as number[]);
      return items.filter((f) => !deleting.has(f.id));
    } catch {
      return items;
    }
  }, [folderData]);

  const clusters = useMemo(
    () => (clusterData?.items ?? []).filter((c) => !c.is_archived),
    [clusterData]
  );

  const isAdmin = user?.role === 'admin';
  const isActive = (href: string, exact = false) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  const badge = ENV_BADGE[ENV_LABEL];

  return (
    <aside
      className={cn(
        'flex shrink-0 flex-col border-r border-border bg-chrome transition-[width] duration-150',
        collapsed ? 'w-[60px]' : 'w-[232px]'
      )}
      aria-label="Navigation"
    >
      <div className={cn('flex items-center gap-2 px-3 pb-2 pt-3', collapsed && 'flex-col px-0')}>
        <Link href="/images" className="flex shrink-0 items-center gap-2" title="SightLab">
          <SightLabLogo size="sm" />
          {!collapsed && <span className="text-[14.5px] font-semibold tracking-tight">SightLab</span>}
        </Link>
        {!collapsed && badge && (
          <span className={cn('truncate whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider', badge.className)}>
            {badge.label}
          </span>
        )}
        <button
          onClick={toggleCollapsed}
          className={cn(
            'grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground',
            !collapsed && 'ml-auto'
          )}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </button>
      </div>

      <div className={cn('flex gap-1.5 px-2.5 pb-2', collapsed && 'flex-col items-center')}>
        <Link
          href="/generate"
          title="Create"
          className={cn(
            'flex h-8 items-center justify-center gap-1.5 rounded-md bg-primary text-[13px] font-medium text-primary-foreground hover:opacity-90',
            collapsed ? 'w-9' : 'flex-1'
          )}
        >
          <Sparkles className="h-4 w-4" />
          {!collapsed && 'Create'}
        </Link>
        <Link
          href="/upload"
          title="Upload"
          className={cn(
            'flex h-8 items-center justify-center gap-1.5 rounded-md border border-input bg-background px-2.5 text-[13px] font-medium hover:bg-accent',
            collapsed && 'w-9 px-0'
          )}
        >
          <Upload className="h-4 w-4" />
          {!collapsed && 'Upload'}
        </Link>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2">
        <GroupLabel collapsed={collapsed}>Library</GroupLabel>
        <div className="space-y-px">
          <NavItem href="/images" icon={ImageIcon} label="All images" active={isActive('/images', true)} collapsed={collapsed} />
          <NavItem href="/clusters" icon={LayoutGrid} label="Clusters" active={isActive('/clusters', true)} collapsed={collapsed} />
        </div>

        {!collapsed && folders.length > 0 && (
          <>
            <GroupLabel href="/images" collapsed={collapsed}>Folders</GroupLabel>
            <div className="space-y-px">
              {folders.slice(0, SIDEBAR_FOLDER_LIMIT).map((f) => (
                <NavItem
                  key={f.id}
                  href={`/images/folder/${f.id}`}
                  icon={FolderOpen}
                  label={f.name}
                  count={f.image_count}
                  active={isActive(`/images/folder/${f.id}`)}
                  collapsed={collapsed}
                />
              ))}
              {folders.length > SIDEBAR_FOLDER_LIMIT && (
                <Link href="/images" className="block px-2 py-1 text-xs text-muted-foreground hover:text-foreground">
                  All {folders.length} folders
                </Link>
              )}
            </div>
          </>
        )}

        {!collapsed && clusters.length > 0 && (
          <>
            <GroupLabel href="/clusters" collapsed={collapsed}>Clusters</GroupLabel>
            <div className="space-y-px">
              {clusters.slice(0, SIDEBAR_CLUSTER_LIMIT).map((c) => (
                <NavItem
                  key={c.id}
                  href={`/clusters/${c.id}`}
                  icon={LayoutGrid}
                  label={c.display_name || c.summary_title || `Cluster ${c.id}`}
                  count={c.size}
                  active={isActive(`/clusters/${c.id}`)}
                  collapsed={collapsed}
                />
              ))}
            </div>
          </>
        )}

        <GroupLabel collapsed={collapsed}>Tools</GroupLabel>
        <div className="space-y-px pb-3">
          <NavItem href="/generate" icon={Sparkles} label="Generate" active={isActive('/generate')} collapsed={collapsed} />
          <NavItem href="/edit" icon={Pencil} label="Edit" active={isActive('/edit')} collapsed={collapsed} />
          <NavItem href="/vision" icon={Eye} label="Vision" active={isActive('/vision')} collapsed={collapsed} />
          <NavItem href="/models" icon={Box} label="Models" active={isActive('/models')} collapsed={collapsed} />
        </div>
      </nav>

      <div className="space-y-px border-t border-border p-2">
        <NavItem href="/jobs" icon={Activity} label="Jobs" active={isActive('/jobs')} collapsed={collapsed} />
        <NavItem href="/billing" icon={CreditCard} label="Billing" active={isActive('/billing')} collapsed={collapsed} />
        <NavItem href="/settings" icon={Settings} label="Settings" active={isActive('/settings')} collapsed={collapsed} />
        {isAdmin && (
          <>
            <NavItem href="/debug" icon={Bug} label="Debug" active={isActive('/debug')} collapsed={collapsed} />
            <NavItem href="/admin" icon={ShieldCheck} label="Admin" active={isActive('/admin')} collapsed={collapsed} />
          </>
        )}

        {user && (
          <div className={cn('flex items-center gap-2 px-1 pt-2', collapsed && 'flex-col')}>
            <span
              className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-violet-500 to-emerald-500 text-xs font-semibold text-white"
              title={user.email}
            >
              {(user.display_name || user.email).charAt(0).toUpperCase()}
            </span>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{user.display_name || user.email}</p>
                {user.display_name && <p className="truncate text-[11px] text-muted-foreground">{user.email}</p>}
              </div>
            )}
            <button
              onClick={logout}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
              title="Sign out"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
