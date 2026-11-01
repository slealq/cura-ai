'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { foldersApi } from '@/lib/api';
import { useMobileSheet } from '@/hooks/useMobileSheet';
import LibraryImage from '@/components/LibraryImage';
import type { Folder } from '@/types';

export default function FoldersPage() {
  const client = useQueryClient();
  const [active, setActive] = useState<Folder | 'new' | null>(null);
  const [name, setName] = useState('');
  const ref = useMobileSheet(!!active, () => setActive(null));
  const { data, isLoading, isError } = useQuery({ queryKey: ['folders', 'mobile-list'], queryFn: () => foldersApi.list({ limit: 200 }) });
  const save = async () => {
    if (!name.trim()) return;
    try {
      if (active === 'new') await foldersApi.create({ name: name.trim() });
      else if (active) await foldersApi.update(active.id, { name: name.trim() });
      setActive(null);
      void client.invalidateQueries({ queryKey: ['folders'] });
    } catch { toast.error('Could not save folder'); }
  };
  return (
    <div>
      <div className="md:hidden flex min-h-12 items-center justify-between">
        <span className="sr-only">Folders</span>
        <button onClick={() => { setActive('new'); setName(''); }}>New</button>
      </div>
      {isLoading && <p role="status">Loading folders…</p>}
      {isError && <p>Could not load folders. Please try again.</p>}
      {data?.items.length === 0 && <p>No folders yet.</p>}
      {data?.items.map(folder => (
        <div key={folder.id} className="flex items-center border-b border-border">
          <Link href={`/images/folder/${folder.id}`} className="flex flex-1 min-h-14 items-center gap-3 py-3">
            {folder.cover_thumbnail_url && <LibraryImage src={folder.cover_thumbnail_url} alt="" className="md:hidden h-12 w-12 rounded object-cover" />}
            <span>{folder.name}<small className="md:hidden block text-muted-foreground">{folder.image_count} images</small></span>
          </Link>
          <button className="md:hidden min-h-12 px-3" aria-label={`Actions for ${folder.name}`} onClick={() => { setActive(folder); setName(folder.name); }}>Options</button>
          <span className="hidden md:block" aria-hidden="true">›</span>
        </div>
      ))}
      {active && (
        <div className="fixed inset-0 z-50 bg-black/50 md:hidden" onClick={() => setActive(null)}>
          <section ref={ref} role="dialog" aria-modal="true" aria-label="Folder actions" className="mobile-sheet absolute inset-x-0 bottom-0 rounded-t-2xl bg-background p-5 space-y-4" onClick={e => e.stopPropagation()}>
            <button className="min-h-10" onClick={() => setActive(null)}>Close</button>
            <label className="block">Folder name<input value={name} onChange={e => setName(e.target.value)} className="mt-2 block w-full rounded border border-border p-3 text-base" /></label>
            <button className="min-h-12" onClick={() => void save()}>{active === 'new' ? 'Create folder' : 'Rename'}</button>
            {active !== 'new' && <Link className="block min-h-12 text-danger" href={`/images/folder/${active.id}?folder_actions=delete`}>Delete folder…</Link>}
          </section>
        </div>
      )}
    </div>
  );
}
