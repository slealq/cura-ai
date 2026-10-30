'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Activity, Search, Zap } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { billingApi, jobsApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { jobLabel } from '@/hooks/useJobNotifications';
import { cn, formatNumber } from '@/lib/utils';
import type { Job } from '@/types';

const ACTIVE_STATUSES = new Set(['pending', 'running']);
const LOW_BALANCE = 100;

function JobRow({ job }: { job: Job }) {
  const active = ACTIVE_STATUSES.has(job.status);
  const pct = job.total_items > 0 ? Math.round((job.progress / job.total_items) * 100) : null;
  return (
    <Link href="/jobs" className="block rounded-md px-2 py-2 hover:bg-muted">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-[13px] font-medium">
          {jobLabel(job)}
          {job.total_items > 1 && <span className="text-muted-foreground"> · {job.total_items} items</span>}
        </span>
        <span
          className={cn(
            'shrink-0 font-mono text-[11px]',
            job.status === 'failed' ? 'text-danger' : active ? 'text-selection' : 'text-muted-foreground'
          )}
        >
          {active ? (pct != null ? `${pct}%` : job.status) : job.status}
        </span>
      </div>
      {active && pct != null && (
        <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-gradient-to-r from-violet-500 via-blue-500 to-emerald-500 transition-[width] duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {job.status === 'failed' && job.error_message && (
        <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">{job.error_message}</p>
      )}
    </Link>
  );
}

function ActivityMenu() {
  const { isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Same key and fetcher as useJobNotifications, so this shares its 5s poll
  const { data } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const jobs = data?.items ?? [];
  const running = jobs.filter((j) => ACTIVE_STATUSES.has(j.status));
  const recent = [...running, ...jobs.filter((j) => !ACTIVE_STATUSES.has(j.status))].slice(0, 6);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        {running.length > 0 ? (
          <span className="h-[7px] w-[7px] animate-pulse rounded-full bg-gradient-to-r from-violet-500 via-blue-500 to-emerald-500" />
        ) : (
          <Activity className="h-4 w-4" />
        )}
        {running.length > 0 ? `${running.length} running` : 'Activity'}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-[360px] rounded-lg border border-border bg-card p-1.5 shadow-[0_16px_40px_-12px_rgb(0_0_0/0.25)]">
          <p className="px-2 pb-1 pt-1.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            Activity
          </p>
          {recent.length === 0 ? (
            <p className="px-2 py-3 text-[13px] text-muted-foreground">
              No jobs yet. Uploads, descriptions, edits and training runs show up here with their progress.
            </p>
          ) : (
            recent.map((job) => <JobRow key={job.id} job={job} />)
          )}
          <div className="mt-1 border-t border-border px-1 pt-1">
            <Link
              href="/jobs"
              onClick={() => setOpen(false)}
              className="block rounded-md px-2 py-1.5 text-[13px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              Open all jobs
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function BalanceChip() {
  const { user } = useAuth();
  const { data } = useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: billingApi.getBalance,
    refetchInterval: 30000,
    enabled: !!user,
  });
  if (!data) return null;
  const available = data.available ?? data.balance - (data.reserved ?? 0);
  const low = available < LOW_BALANCE;
  return (
    <Link
      href="/billing"
      title={
        data.reserved > 0
          ? `${formatNumber(data.reserved, 0)} sparks reserved for running jobs`
          : 'Sparks balance'
      }
      className={cn(
        'flex h-8 items-center gap-1.5 rounded-full px-2.5 font-mono text-[12.5px] font-medium tabular-nums',
        low ? 'bg-danger/10 text-danger' : 'bg-muted hover:bg-accent'
      )}
    >
      <Zap className={cn('h-3.5 w-3.5', low ? 'text-danger' : 'text-amber-500')} />
      {formatNumber(available, 0)}
      {low && <span className="font-sans text-[12px]">· Top up</span>}
    </Link>
  );
}

export default function Header() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <form onSubmit={handleSearch} className="w-full max-w-md" role="search">
        <label className="flex h-8 items-center gap-2 rounded-lg border border-border bg-muted px-2.5 text-muted-foreground focus-within:border-selection focus-within:ring-2 focus-within:ring-selection/20">
          <Search className="h-4 w-4 shrink-0" />
          <input
            type="text"
            placeholder="Search tags, descriptions, prompts…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search images"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none"
            style={{ backgroundColor: 'transparent' }}
          />
        </label>
      </form>
      <div className="ml-auto flex items-center gap-1.5">
        <ActivityMenu />
        <BalanceChip />
      </div>
    </header>
  );
}
