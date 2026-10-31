'use client';
import Link from 'next/link';
import { useState } from 'react';
import { X, Sparkles } from 'lucide-react';
import { useMobileSheet } from '@/hooks/useMobileSheet';
import type { Cluster, ClusterListResponse } from '@/types';
import LibraryImage from './LibraryImage';
import ClusterTools, { clusterTitle } from './ClusterTools';

export default function ClusterInspector({ selected, overview, onClear, onDismiss }: {
  selected: Cluster[]; overview?: ClusterListResponse['overview']; onClear: () => void; onDismiss?: () => void;
}) {
  const ref = useMobileSheet(!!onDismiss, () => onDismiss?.());
  const [swipe, setSwipe] = useState(0);
  const largest = overview?.largest || [];
  return <aside ref={ref} aria-label="Cluster inspector" role={onDismiss ? 'dialog' : undefined} aria-modal={onDismiss ? true : undefined} className="flex h-full flex-col border-l border-border bg-background">
    <header className="flex items-center justify-between border-b border-border p-4" onTouchStart={e => setSwipe(e.touches[0].clientY)} onTouchEnd={e => { if (e.changedTouches[0].clientY - swipe > 80) onDismiss?.(); }}>
      <h2 className="flex items-center gap-2 font-medium"><Sparkles className="h-4 w-4" />{selected.length ? `${selected.length} selected` : 'All clusters'}</h2>
      {selected.length > 0 && <button className="text-sm text-muted-foreground" onClick={onClear}>Clear</button>}
      {onDismiss && <button aria-label="Close inspector" onClick={onDismiss}><X className="h-4 w-4" /></button>}
    </header>
    <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
      {selected.length ? <>
        <div className="grid grid-cols-4 gap-0.5 overflow-hidden rounded-md">{selected.flatMap(c => (c.preview_images || []).slice(0, 2)).slice(0, 8).map((image, i) => <LibraryImage key={`${image.id}-${i}`} src={image.thumbnail_url} alt="" className="aspect-square w-full object-cover" />)}</div>
        <div className="flex justify-between"><span>Images in selection</span><span className="font-mono text-muted-foreground">{selected.reduce((n, c) => n + c.size, 0).toLocaleString()}</span></div>
        <ClusterTools clusters={selected} onDone={onClear} />
      </> : <>
        {([['Clusters', overview?.clusters ?? 0], ['Images grouped', overview?.grouped ?? 0], ["Didn't fit", overview?.unclustered?.size ?? 0]] as const).map(([label, value]) => <div key={label} className="flex justify-between"><span>{label}</span><span className="font-mono text-muted-foreground">{value.toLocaleString()}</span></div>)}
        <h3 className="text-xs text-muted-foreground">Largest clusters</h3>
        {largest.map(c => <Link className="block" key={c.id} href={`/clusters/${c.id}`}><div className="flex justify-between gap-3"><span className="truncate">{clusterTitle(c)}</span><span className="font-mono text-muted-foreground">{c.size}</span></div><div className="mt-1 h-1 rounded bg-muted"><div className="h-full rounded bg-foreground" style={{ width: `${100 * c.size / Math.max(largest[0]?.size || 1, 1)}%` }} /></div></Link>)}
        <p className="text-muted-foreground">Select clusters using the circles to merge, train, organize or archive.</p>
      </>}
    </div>
  </aside>;
}
