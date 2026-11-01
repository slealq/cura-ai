'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { billingApi, jobsApi } from '@/lib/api';
import { formatNumber } from '@/lib/utils';

export default function MobileStatus() {
  const pathname = usePathname();
  const previous = useRef<Map<number, string>>(new Map());
  const initialized = useRef(false);
  const [unread, setUnread] = useState(0);
  const { data: balance } = useQuery({ queryKey: ['billing', 'balance'], queryFn: billingApi.getBalance, refetchInterval: 30000 });
  const { data } = useQuery({ queryKey: ['jobs'], queryFn: () => jobsApi.list({ limit: 50 }), refetchInterval: 5000 });
  useEffect(() => {
    if (!data) return;
    let added = 0;
    for (const job of data.items) {
      const prev = previous.current.get(job.id);
      if (initialized.current && (job.status === 'completed' || job.status === 'failed') && prev !== job.status) added++;
      previous.current.set(job.id, job.status);
    }
    initialized.current = true;
    setUnread(count => pathname === '/jobs' ? 0 : count + added);
  }, [data, pathname]);
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
