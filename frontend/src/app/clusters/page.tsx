'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { clustersApi, jobsApi } from '@/lib/api';
import ClusteringRunDialog from '@/components/ClusteringRunDialog';
import ClusterStrip from '@/components/ClusterStrip';
import ClusterInspector from '@/components/ClusterInspector';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;
const button = 'rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-40';

export default function ClustersPage() {
  const client = useQueryClient();
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');
  const [sort, setSort] = useState<'size' | 'name'>('size');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showRun, setShowRun] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [mobilePanel, setMobilePanel] = useState(false);
  const [wide, setWide] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1100px)');
    const update = () => setWide(media.matches);
    update(); media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => { const timer = setTimeout(() => { setTerm(search); setSelected(new Set()); }, 200); return () => clearTimeout(timer); }, [search]);
  const query = useInfiniteQuery({
    queryKey: ['clusters', 'strips', term, sort],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => clustersApi.list({ skip: pageParam, limit: PAGE_SIZE, search: term, sort }),
    getNextPageParam: last => last.skip + last.items.length < last.total ? last.skip + last.items.length : undefined,
    enabled: jobId === null,
    refetchInterval: query => query.state.data?.pages.some(page => page.items.some(c => !c.summary_title)) ? 5000 : false,
  });
  const job = useQuery({ queryKey: ['cluster-job', jobId], queryFn: () => jobsApi.get(jobId!), enabled: jobId !== null, refetchInterval: 3000 });
  useEffect(() => {
    if (jobId === null || !job.data || !['completed', 'failed'].includes(job.data.status)) return;
    if (job.data.status === 'completed') toast.success('Clustering completed — summarizing clusters…');
    else toast.error('Clustering failed', { description: job.data.error_message || `Job #${jobId}` });
    setJobId(null); setSelected(new Set());
    void client.invalidateQueries({ queryKey: ['clusters'] });
  }, [job.data, jobId, client]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    if (!sentinel.current || !hasNextPage) return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage(); }, { rootMargin: '400px' });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const items = query.data?.pages.flatMap(page => page.items).filter(c => !c.is_unclustered) || [];
  const overview = query.data?.pages[0]?.overview;
  const selection = items.filter(c => selected.has(c.id));
  const pending = items.filter(c => !c.summary_title).length;
  const clear = () => setSelected(new Set());
  return <div className="flex min-w-0 items-start gap-5">
    <main className="min-w-0 flex-1">
      <header className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-xl font-semibold">Clusters</h1><span className="font-mono text-sm text-muted-foreground">{overview?.clusters ?? '—'}</span>
        <input aria-label="Search clusters" type="search" placeholder="Search clusters" value={search} onChange={e => setSearch(e.target.value)} className="order-last w-full min-w-0 basis-full rounded-md border border-input px-3 py-1.5 text-sm md:order-none md:ml-auto md:w-auto md:flex-1 md:basis-auto md:max-w-52" />
        <div className="flex rounded-md bg-muted p-0.5" role="group" aria-label="Sort clusters">{([['size', 'Largest'], ['name', 'A–Z']] as const).map(([value, label]) => <button key={value} aria-pressed={sort === value} onClick={() => setSort(value)} className={cn('rounded px-2 py-1 text-xs', sort === value && 'bg-background shadow-sm')}>{label}</button>)}</div>
        <button className={button} onClick={() => setShowRun(true)} disabled={jobId !== null}>Recluster</button>
        {!wide && <button className={button} onClick={() => setMobilePanel(true)}>Inspector{selection.length ? ` · ${selection.length}` : ''}</button>}
      </header>
      {jobId !== null ? <div className="grid h-64 place-content-center gap-3 text-center text-sm text-muted-foreground"><Loader2 className="mx-auto h-6 w-6 animate-spin" /><p>Clustering in progress…</p><p>New clusters will appear automatically when complete</p></div> : <>
        {query.isLoading && <div className="grid h-64 place-items-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}
        {query.isError && <div role="alert" className="py-12 text-sm text-muted-foreground">Failed to load clusters. <button className="underline" onClick={() => query.refetch()}>Retry</button></div>}
        {pending > 0 && <p role="status" className="mb-3 flex items-center gap-2 rounded-md bg-muted p-3 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Summarizing clusters… ({pending} remaining)</p>}
        {!query.isLoading && !query.isError && !items.length && <div className="py-16 text-center text-sm text-muted-foreground">{term ? 'No clusters match that search.' : overview?.unclustered ? 'No grouped clusters yet. Review your unclustered images below.' : 'No clusters yet. Upload some images and run clustering to get started.'}</div>}
        {items.map(cluster => <ClusterStrip key={cluster.id} cluster={cluster} selected={selected.has(cluster.id)} onSelect={() => setSelected(previous => { const next = new Set(previous); if (next.has(cluster.id)) next.delete(cluster.id); else next.add(cluster.id); return next; })} />)}
        <div ref={sentinel} className="flex h-8 justify-center">{isFetchingNextPage && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}</div>
        {overview?.unclustered && <Link className="flex items-center justify-between gap-3 rounded-md bg-muted px-3 py-2.5 text-sm" href={`/clusters/${overview.unclustered.id}`}><span>{overview.unclustered.size.toLocaleString()} images didn&apos;t fit any cluster</span><span className="text-muted-foreground">Review</span></Link>}
      </>}
    </main>
    {(wide || mobilePanel) && <>
      {!wide && <button aria-label="Dismiss inspector" className="fixed inset-0 z-40 bg-foreground/20" onClick={() => setMobilePanel(false)} />}
      <div className={cn('library-inspector sticky top-4 h-[calc(100vh-120px)] w-[300px] shrink-0', !wide && 'fixed inset-0 z-50 h-full w-full bg-background sm:left-auto sm:w-[340px]')}>
        <ClusterInspector selected={selection} overview={overview} onClear={clear} onDismiss={!wide ? () => setMobilePanel(false) : undefined} />
      </div>
    </>}
    {showRun && <ClusteringRunDialog hasClusters={(overview?.clusters || 0) > 0 || !!overview?.unclustered} onClose={() => setShowRun(false)} onStarted={id => { setShowRun(false); setJobId(id); clear(); toast.success('Clustering job started', { action: { label: 'View Jobs', onClick: () => { window.location.href = '/jobs'; } } }); }} />}
  </div>;
}
