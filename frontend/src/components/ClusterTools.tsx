'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { clustersApi } from '@/lib/api';
import type { Cluster } from '@/types';
import AddToFolderDialog from './AddToFolderDialog';
import TrainLoraModal from '@/app/models/components/TrainLoraModal';

export const clusterTitle = (c: Cluster) => c.display_name || c.summary_title || `Cluster ${c.id}`;
export const clusterBullets = (c: Cluster) => (c.summary_description || '').split('\n').map(s => s.replace(/^\s*-\s*/, '').trim()).filter(Boolean);
const button = 'rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent disabled:opacity-40';

export default function ClusterTools({ clusters, detail = false, onDone }: { clusters: Cluster[]; detail?: boolean; onDone?: () => void }) {
  const client = useQueryClient();
  const router = useRouter();
  const [train, setTrain] = useState(false);
  const [folderIds, setFolderIds] = useState<number[] | null>(null);
  const [rename, setRename] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    void action().then(async () => {
      toast.success(label);
      await client.invalidateQueries();
    }).catch((error: Error) => toast.error(error.message)).finally(() => setBusy(false));
  };
  return <>
    <div className="grid grid-cols-2 gap-2">
      {!detail && <button className={button} disabled={busy || clusters.length < 2} onClick={() => run('Clusters merged', async () => { await clustersApi.merge(clusters.map(c => c.id)); onDone?.(); })}>Merge</button>}
      <button className={button} disabled={busy} onClick={() => setTrain(true)}>Train model</button>
      <button className={button} disabled={busy} onClick={() => run('Images ready to add', async () => {
        const ids = new Set<number>();
        for (const cluster of clusters) {
          const result = await clustersApi.get(cluster.id);
          result.images.forEach(image => ids.add(image.id));
        }
        setFolderIds(Array.from(ids));
      })}>Add to folder</button>
      <button className={button} disabled={busy} onClick={() => run('Pins updated', async () => {
        for (const c of clusters) if (detail || !c.is_pinned) await clustersApi.togglePin(c.id);
      })}>{detail && clusters[0]?.is_pinned ? 'Unpin' : 'Pin'}</button>
      {clusters.map(c => <a className={button} key={c.id} href={clustersApi.exportCluster(c.id, 'zip')}>Export{clusters.length > 1 ? ` · ${clusterTitle(c)}` : ''}</a>)}
      {detail && <>
        <button className={button} disabled={busy} onClick={() => setRename(clusterTitle(clusters[0]))}>Rename</button>
        <button className={button} disabled={busy} onClick={() => run('Summary queued', () => clustersApi.summarize(clusters[0].id))}>Refresh summary</button>
      </>}
      <button className={button} disabled={busy} onClick={() => run('Clusters archived', async () => {
        for (const c of clusters) await clustersApi.archive(c.id);
        onDone?.();
        if (detail) router.push('/clusters');
      })}>Archive</button>
    </div>
    {rename !== null && <form className="space-y-2" onSubmit={e => { e.preventDefault(); if (rename.trim()) run('Cluster renamed', async () => { await clustersApi.rename(clusters[0].id, rename.trim()); setRename(null); }); }}>
      <input aria-label="Cluster name" className="w-full rounded border border-input p-2" value={rename} onChange={e => setRename(e.target.value)} autoFocus />
      <button className={button} disabled={busy || !rename.trim()}>Save</button> <button type="button" className={button} onClick={() => setRename(null)}>Cancel</button>
    </form>}
    {train && <TrainLoraModal open sourceClusters={clusters} onClose={() => setTrain(false)} />}
    {folderIds && <AddToFolderDialog imageIds={folderIds} onClose={() => setFolderIds(null)} onDone={() => setFolderIds(null)} />}
  </>;
}
