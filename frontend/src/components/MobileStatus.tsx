'use client';

import Link from 'next/link';
import { useNotifications } from '@/contexts/NotificationContext';
import { useQuery } from '@tanstack/react-query';
import { billingApi, jobsApi } from '@/lib/api';
import { formatNumber } from '@/lib/utils';

export default function MobileStatus() {
  const { unread } = useNotifications();
  const { data: balance } = useQuery({ queryKey: ['billing', 'balance'], queryFn: billingApi.getBalance, refetchInterval: 30000 });
  const { data } = useQuery({ queryKey: ['jobs'], queryFn: () => jobsApi.list({ limit: 50 }), refetchInterval: 5000 });
  const running = data?.items.filter(job => job.status === 'pending' || job.status === 'running').length ?? 0;
  const available = balance ? balance.available ?? balance.balance - (balance.reserved ?? 0) : null;
  return (
    <div className="ml-auto flex shrink-0 items-center gap-1 text-xs">
      <Link href="/billing" className="flex min-h-10 items-center rounded-full border border-border px-2 font-mono" aria-label="Available sparks, open Billing">
        {available === null ? '…' : formatNumber(available, 0)} sparks
      </Link>
      {(running > 0 || unread > 0) && (
        <Link href="/jobs" className="flex min-h-10 items-center gap-1 rounded-full border border-border px-2">
          <span className={`h-1.5 w-1.5 rounded-full bg-selection ${running ? 'animate-pulse' : ''}`} />
          {running || unread} {running ? 'running' : 'new'}
        </Link>
      )}
    </div>
  );
}
