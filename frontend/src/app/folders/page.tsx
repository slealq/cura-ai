'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { foldersApi } from '@/lib/api';

export default function FoldersPage() {
  const { data, isLoading, isError } = useQuery({ queryKey: ['folders', 'mobile-list'], queryFn: () => foldersApi.list({ limit: 200 }) });
  return (
    <div>
      {isLoading && <p role="status">Loading folders…</p>}
      {isError && <p>Could not load folders. Please try again.</p>}
      {data?.items.length === 0 && <p>No folders yet.</p>}
      {data?.items.map(folder => (
        <Link key={folder.id} href={`/images/folder/${folder.id}`} className="flex min-h-14 items-center justify-between border-b border-border py-3">
          {folder.name}<span aria-hidden="true">›</span>
        </Link>
      ))}
    </div>
  );
}
