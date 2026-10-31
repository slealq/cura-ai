'use client';

import LibraryImage from '@/components/LibraryImage';

import { useModelCatalog } from '@/hooks/useModelCatalog';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useQuery, useQueries, useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, XCircle, Check, RotateCcw, Wrench, Zap, X, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { jobsApi, imagesApi, generationApi } from '@/lib/api';
import { cn, formatDate, formatDuration } from '@/lib/utils';
import type { BatchJobImage, Job } from '@/types';

const JOB_TYPE_LABELS: Record<string, string> = {
  reprocess: 'Describe',
  batch_reprocess: 'Batch Describe',
  batch_describe: 'Batch Describe',
};

function jobTypeLabel(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] || jobType.replaceAll('_', ' ');
}

export default function JobsPage() {
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState<'All' | 'Running' | 'Failed' | 'Done'>('All');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showResults, setShowResults] = useState(false);
  const statuses = filter === 'Running' ? ['running', 'pending'] : filter === 'Failed' ? ['failed'] : filter === 'Done' ? ['completed'] : [undefined];
  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['jobs', 'workbench', filter],
    queryFn: async ({ pageParam }) => {
      const pages = await Promise.all(statuses.map(status => jobsApi.list({ status, skip: pageParam, limit: 50 })));
      return { items: pages.flatMap(page => page.items), more: pages.some(page => page.skip + page.items.length < page.total), skip: pageParam };
    },
    initialPageParam: 0,
    getNextPageParam: page => page.more ? page.skip + 50 : undefined,
    refetchInterval: 5000,
  });
  const counts = useQueries({ queries: [undefined, 'running', 'pending', 'failed', 'completed'].map(status => ({
    queryKey: ['jobs', 'count', status],
    queryFn: () => jobsApi.list({ status, limit: 1 }),
    refetchInterval: 10000,
  })) });
  const count = (index: number) => counts[index].data?.total;
  const filterCounts = { All: count(0), Running: count(1) != null && count(2) != null ? count(1)! + count(2)! : undefined, Failed: count(3), Done: count(4) };
  const jobs = { items: (data?.pages.flatMap(page => page.items) ?? []).sort((a, b) => b.created_at.localeCompare(a.created_at)) };
  const { data: selectedJob, isError: detailError } = useQuery({
    queryKey: ['jobs', 'detail', selectedId],
    queryFn: () => jobsApi.get(selectedId!),
    enabled: selectedId != null,
    refetchInterval: 5000,
  });
  const deleteMutation = useMutation({
    mutationFn: jobsApi.delete,
    onSuccess: () => { setSelectedId(null); toast.success('Job deleted'); queryClient.invalidateQueries({ queryKey: ['jobs'] }); },
    onError: () => toast.error('Could not delete job'),
  });

  const cancelJobMutation = useMutation({
    mutationFn: jobsApi.cancel,
    onSuccess: () => {
      toast.success('Job cancelled');
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to cancel job'),
  });

  const retryJobMutation = useMutation({
    mutationFn: (jobId: number) => jobsApi.retry(jobId),
    onSuccess: (data) => {
      toast.success('Job retry started', { description: `New Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => toast.error('Retry failed', { description: err.message }),
  });

  const recoverMutation = useMutation({
    mutationFn: (loraId: number) => generationApi.recoverLoraTraining(loraId),
    onSuccess: (data) => {
      if (data.status === 'recovered') {
        toast.success('Training recovered successfully');
      } else if (data.status === 'polling_resumed') {
        toast.success('Polling resumed', { description: `fal.ai status: ${data.fal_status}` });
      } else if (data.status === 'failed') {
        toast.error('Training had failed on fal.ai', { description: data.error });
      }
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => toast.error('Recovery failed', { description: err.message }),
  });

  const retryMutation = useMutation({
    mutationFn: (loraId: number) => generationApi.retryLoraTraining(loraId),
    onSuccess: (data) => {
      toast.success('Training retry started', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => toast.error('Retry failed', { description: err.message }),
  });

  const actions = (job: Job) => (
    <div className="flex flex-wrap items-center gap-2">
      {['pending', 'running'].includes(job.status) && <button disabled={cancelJobMutation.isPending} onClick={() => cancelJobMutation.mutate(job.id)} className="rounded-md border border-input px-3 py-1.5 text-sm text-danger disabled:opacity-50">Cancel</button>}
      {job.status === 'failed' && job.job_type !== 'lora_train' && <button disabled={retryJobMutation.isPending} onClick={() => retryJobMutation.mutate(job.id)} className="rounded-md border border-input px-3 py-1.5 text-sm disabled:opacity-50">Retry</button>}
      <LoraJobActions job={job} onRecover={id => recoverMutation.mutate(id)} onRetry={id => retryMutation.mutate(id)} isRecoverPending={recoverMutation.isPending} isRetryPending={retryMutation.isPending} />
      {!['pending', 'running'].includes(job.status) && <button disabled={deleteMutation.isPending} onClick={() => { if (confirm(`Delete job #${job.id}?`)) deleteMutation.mutate(job.id); }} className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-danger hover:bg-danger/10 disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" />Delete</button>}
    </div>
  );

  return (
    <div className="flex items-start gap-5">
      <div className="min-w-0 flex-1 space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
        <div role="group" aria-label="Job status" className="inline-flex flex-wrap gap-1 rounded-lg bg-muted p-1">
          {(['All', 'Running', 'Failed', 'Done'] as const).map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)} className={cn('rounded-md px-3 py-1.5 text-sm', filter === value ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
            {value} <span className="ml-1 font-mono text-xs tabular-nums text-muted-foreground">{filterCounts[value] ?? '…'}</span>
          </button>)}
        </div>
        <p className="text-xs text-muted-foreground">Running includes queued jobs. Cancelled jobs appear under All.</p>
        {isLoading ? <div className="grid h-64 place-items-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          : isError ? <div className="rounded-lg border border-border p-5"><p>Could not load jobs.</p><button onClick={() => refetch()} className="mt-2 text-sm underline">Try again</button></div>
          : jobs.items.length === 0 ? <div className="grid h-64 place-items-center text-sm text-muted-foreground">No jobs in this view</div>
          : <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-chrome text-xs text-muted-foreground"><tr>{['Job', 'Status', 'Progress', 'Result / error', 'Cost', 'Started'].map(label => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {jobs.items.map(job => <tr key={job.id} onClick={() => { setSelectedId(job.id); setShowResults(false); }} className={cn('cursor-pointer hover:bg-accent', selectedId === job.id && 'bg-selection-soft')}>
                  <td className="px-3 py-2"><button onClick={event => { event.stopPropagation(); setSelectedId(job.id); setShowResults(false); }} className="text-left hover:underline" aria-label={`Inspect job ${job.id}`}><span className="font-mono text-xs text-muted-foreground">#{job.id}</span> <span className="capitalize">{jobTypeLabel(job.job_type)}</span></button></td>
                  <td className="whitespace-nowrap px-3 py-2"><JobStatus status={job.status} /></td>
                  <td className="min-w-[130px] px-3 py-2"><JobProgress job={job} /></td>
                  <td className="max-w-[220px] truncate px-3 py-2 text-muted-foreground" title={job.error_message || job.image_filename || undefined}>{job.error_message ? <span className="text-danger">{job.error_message}</span> : job.image_filename || (job.status === 'completed' ? 'View results' : '—')}</td>
                  <td className="px-3 py-2"><JobCost job={job} /></td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">{job.started_at ? formatDate(job.started_at) : 'Queued'}</td>
                </tr>)}
              </tbody>
            </table>
          </div>}
        {hasNextPage && <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage} className="rounded-md border border-input px-3 py-2 text-sm disabled:opacity-50">{isFetchingNextPage ? 'Loading…' : 'Load more jobs'}</button>}
      </div>
      <aside aria-label="Job inspector" className={cn('rounded-lg border border-border bg-chrome p-4 text-sm', selectedId != null ? 'fixed inset-0 z-40 overflow-y-auto min-[1100px]:sticky min-[1100px]:top-4 min-[1100px]:z-auto min-[1100px]:max-h-[calc(100vh-120px)] min-[1100px]:w-[340px] min-[1100px]:shrink-0' : 'sticky top-4 hidden w-[340px] shrink-0 min-[1100px]:block')}>
        {selectedId == null ? <p className="text-muted-foreground">Select a job to view details, results, and actions.</p> : <div className="space-y-4">
          <div className="flex items-center justify-between"><h2 className="font-semibold">Job #{selectedId}</h2><button onClick={() => setSelectedId(null)} aria-label="Close job inspector" className="rounded p-1 hover:bg-accent"><X className="h-4 w-4" /></button></div>
          {detailError ? <p className="text-danger">Could not load job details.</p> : !selectedJob ? <Loader2 className="h-5 w-5 animate-spin" /> : <>
            <div className="flex items-center justify-between gap-2"><span className="capitalize">{jobTypeLabel(selectedJob.job_type)}</span><JobStatus status={selectedJob.status} /></div>
            <JobProgress job={selectedJob} />
            {actions(selectedJob)}
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs">
              <dt className="text-muted-foreground">Created</dt><dd>{formatDate(selectedJob.created_at)}</dd>
              <dt className="text-muted-foreground">Started</dt><dd>{selectedJob.started_at ? formatDate(selectedJob.started_at) : 'Queued'}</dd>
              <dt className="text-muted-foreground">Finished</dt><dd>{selectedJob.completed_at ? formatDate(selectedJob.completed_at) : '—'}</dd>
              <dt className="text-muted-foreground">Model</dt><dd><JobModel job={selectedJob} /></dd>
              <dt className="text-muted-foreground">Cost</dt><dd><JobCost job={selectedJob} /></dd>
            </dl>
            {selectedJob.parameters?.lora_model_id != null && <Link className="block hover:underline" href="/models">View model #{String(selectedJob.parameters.lora_model_id)}</Link>}
            {selectedJob.image_id != null && <Link className="block hover:underline" href={`/images?image_id=${selectedJob.image_id}`}>Open {selectedJob.image_filename || `image #${selectedJob.image_id}`}</Link>}
            {['batch_reprocess', 'batch_describe'].includes(selectedJob.job_type) && <BatchImagesPill key={selectedJob.id} job={selectedJob} />}
            {selectedJob.job_type === 'ingest' && <IngestSummaryPill job={selectedJob} />}
            {selectedJob.error_message && <p className="break-words rounded-md bg-danger/10 p-3 text-danger">{selectedJob.error_message}</p>}
            <details className="rounded-md border border-border p-3"><summary className="cursor-pointer font-medium">Parameters</summary><pre className="mt-2 overflow-x-auto text-xs">{JSON.stringify(selectedJob.parameters, null, 2)}</pre></details>
            <button aria-expanded={showResults} onClick={() => setShowResults(value => !value)} className="rounded-md border border-input px-3 py-2">{showResults ? 'Hide results' : 'Show results'}</button>
            {showResults && <section className="space-y-2 rounded-md border border-border p-3"><h3 className="font-medium">Results</h3><JobResultLinks job={selectedJob} /><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{selectedJob.result ? JSON.stringify(selectedJob.result, null, 2) : 'No results yet'}</pre></section>}
          </>}
        </div>}
      </aside>
    </div>
  );
}

function JobStatus({ status }: { status: string }) {
  const config = status === 'completed' ? { label: 'Done', color: 'bg-success/10 text-success' }
    : status === 'running' || status === 'pending' ? { label: status === 'pending' ? 'Queued' : 'Running', color: 'bg-selection-soft text-selection' }
    : status === 'failed' ? { label: 'Failed', color: 'bg-danger/10 text-danger' }
    : { label: status === 'cancelled' ? 'Cancelled' : 'Needs attention', color: 'bg-warning/10 text-warning' };
  return <span className={cn('inline-flex rounded-full px-2 py-0.5 text-xs font-medium', config.color)}>{config.label}</span>;
}

function JobResultLinks({ job }: { job: Job }) {
  const result = job.result;
  const generated = Array.isArray(result?.generated_image_ids) ? result.generated_image_ids.filter((id): id is number => typeof id === 'number') : typeof result?.generated_image_id === 'number' ? [result.generated_image_id] : [];
  return <div className="space-y-1">
    {generated.map(id => <a key={id} href={generationApi.getImageUrl(id)} target="_blank" rel="noopener noreferrer" className="block hover:underline">Open generated image #{id}</a>)}
    {typeof result?.evaluation_id === 'number' && typeof job.parameters?.lora_model_id === 'number' && <Link href={`/models/${job.parameters.lora_model_id}/evaluations/${result.evaluation_id}`} className="block hover:underline">Open evaluation</Link>}
    {job.job_type.includes('generate') || job.job_type.includes('edit') ? <Link href={job.job_type.includes('edit') ? "/images?source=edited" : "/images?source=generated"} className="block hover:underline">View image library</Link> : null}
  </div>;
}

function BatchImagesPill({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  const [images, setImages] = useState<BatchJobImage[] | null>(null);
  const [loading, setLoading] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  const imageCount = (job.result as Record<string, unknown> | null)?.image_ids
    ? ((job.result as Record<string, unknown>).image_ids as number[]).length
    : job.total_items;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const handleOpen = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (!images) {
      setLoading(true);
      try {
        const data = await jobsApi.getJobImages(job.id);
        setImages(data);
      } catch {
        setImages([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={handleOpen}
        className="text-xs text-primary bg-primary/10 hover:bg-primary/20 px-2 py-0.5 rounded font-medium transition-colors"
      >
        {imageCount} images
      </button>

      {open && (
        <div className="absolute z-50 top-full mt-1 left-0 bg-card border border-border rounded-lg shadow-lg p-3 w-64 max-h-80 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : images && images.length > 0 ? (
            <div className="space-y-2">
              {images.map((img) => (
                <Link
                  key={img.id}
                  href={`/images?image_id=${img.id}`}
                  className="flex items-center gap-2 hover:bg-muted rounded p-1 transition-colors"
                >
                  {img.thumbnail ? (
                    <LibraryImage
                      src={imagesApi.getThumbnailUrl(img.thumbnail)}
                      alt=""
                      className="h-8 w-8 rounded object-cover flex-shrink-0"
                    />
                  ) : (
                    <div className="h-8 w-8 rounded bg-muted flex-shrink-0" />
                  )}
                  <span className="text-xs truncate text-primary">
                    {img.original_filename || `#${img.id}`}
                  </span>
                </Link>
              ))}

            </div>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-4">No images found</p>
          )}
        </div>
      )}
    </div>
  );
}

function IngestSummaryPill({ job }: { job: Job }) {
  const result = job.result as Record<string, unknown> | null;
  if (!result) return null;

  const total = (result.total_received as number) ?? 0;
  const nNew = (result.new_count as number) ?? 0;
  const nDup = (result.duplicate_count as number) ?? 0;
  const nFail = (result.failed_count as number) ?? 0;

  const parts: string[] = [];
  if (nNew > 0) parts.push(`${nNew} new`);
  if (nDup > 0) parts.push(`${nDup} dup`);
  if (nFail > 0) parts.push(`${nFail} failed`);
  const tooltip = parts.join(', ') || `${total} received`;

  return (
    <span
      className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded font-medium cursor-default"
      title={tooltip}
    >
      {total} received
    </span>
  );
}

function LoraJobActions({
  job,
  onRecover,
  onRetry,
  isRecoverPending,
  isRetryPending,
}: {
  job: Job;
  onRecover: (loraId: number) => void;
  onRetry: (loraId: number) => void;
  isRecoverPending: boolean;
  isRetryPending: boolean;
}) {
  if (job.job_type !== 'lora_train') return null;

  const loraId = (job.parameters?.lora_model_id as number) ?? null;
  if (!loraId) return null;

  // Show recover button for running jobs older than 5 minutes
  if (job.status === 'running' && job.started_at) {
    const elapsed = Date.now() - new Date(job.started_at).getTime();
    if (elapsed > 5 * 60 * 1000) {
      return (
        <button
          onClick={() => onRecover(loraId)}
          disabled={isRecoverPending}
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
            'border border-amber-300 text-amber-700 hover:bg-amber-50',
            'dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/30',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
          title="Check fal.ai status and recover if completed"
        >
          <Wrench className="h-3 w-3" />
          Recover
        </button>
      );
    }
  }

  // Show retry button for failed jobs
  if (job.status === 'failed') {
    return (
      <button
        onClick={() => onRetry(loraId)}
        disabled={isRetryPending}
        className={cn(
          'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
          'border border-border text-foreground hover:bg-muted',
          'disabled:opacity-50 disabled:cursor-not-allowed'
        )}
        title="Retry training from scratch"
      >
        <RotateCcw className="h-3 w-3" />
        Retry
      </button>
    );
  }

  return null;
}

function JobModel({ job }: { job: Job }) {
  const { data: catalog } = useModelCatalog();
  const models = [...(catalog?.generation ?? []), ...(catalog?.edit ?? [])];
  const params = job.parameters as Record<string, unknown> | null;
  const baseModel = params?.base_model as string | undefined;
  const editModel = params?.edit_model as string | undefined;
  const model = baseModel || editModel;

  if (!model) return <span className="text-xs text-muted-foreground">-</span>;

  const displayName = models.find(m => m.key === model || m.endpoint === model)?.label || model;
  return (
    <span className="text-xs font-medium text-muted-foreground" title={model}>
      {displayName}
    </span>
  );
}

function JobCost({ job }: { job: Job }) {
  const cost = job.charged_sparks ?? job.charged_cost;
  if (cost == null) return <span className="text-xs text-muted-foreground">-</span>;

  const sparks = Math.round(cost);

  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-warning">
      <Zap className="h-3 w-3" />
      {sparks}
    </span>
  );
}

function JobProgress({ job }: { job: Job }) {
  const isIndividual = job.total_items <= 1;

  // Compute duration string for completed/failed jobs
  const durationStr = (job.status === 'completed' || job.status === 'failed') && job.created_at && job.completed_at
    ? formatDuration((new Date(job.completed_at + (job.completed_at.endsWith('Z') ? '' : 'Z')).getTime() - new Date(job.created_at + (job.created_at.endsWith('Z') ? '' : 'Z')).getTime()) / 1000)
    : null;

  if (isIndividual) {
    if (job.status === 'completed') {
      return (
        <span className="flex items-center gap-1.5">
          <Check className="h-4 w-4 text-success" />
          {durationStr && <span className="text-xs text-muted-foreground">{durationStr}</span>}
        </span>
      );
    }
    if (job.status === 'failed') {
      return <XCircle className="h-4 w-4 text-danger" />;
    }
    if (job.status === 'running') {
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
    }
    return <span className="text-muted-foreground text-xs">Queued</span>;
  }

  if (job.total_items > 0) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden max-w-[100px]">
          <div
            className="h-full bg-selection transition-all"
            style={{
              width: `${(job.progress / job.total_items) * 100}%`,
            }}
          />
        </div>
        <span className="text-xs text-muted-foreground">
          {job.progress}/{job.total_items}
          {durationStr && ` · ${durationStr}`}
        </span>
      </div>
    );
  }

  return <span className="text-muted-foreground">-</span>;
}
