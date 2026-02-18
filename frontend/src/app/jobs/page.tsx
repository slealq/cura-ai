'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, XCircle, RefreshCw, Tag, FileText, Cpu, Sparkles, Check, AlertTriangle, RotateCcw, Wrench, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { jobsApi, clustersApi, imagesApi, generationApi } from '@/lib/api';
import { cn, formatDate, getStatusColor } from '@/lib/utils';
import type { BatchJobImage, Job } from '@/types';

export default function JobsPage() {
  const queryClient = useQueryClient();

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
  });

  const { data: stats } = useQuery({
    queryKey: ['pipeline-stats'],
    queryFn: imagesApi.getStats,
    refetchInterval: 5000,
  });

  const triggerPipelineMutation = useMutation({
    mutationFn: jobsApi.triggerFullPipeline,
    onSuccess: (data) => {
      toast.success('Full pipeline started', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start pipeline'),
  });

  const triggerClusteringMutation = useMutation({
    mutationFn: () => clustersApi.recluster(),
    onSuccess: (data) => {
      toast.success('Clustering started', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start clustering'),
  });

  const triggerBatchTagMutation = useMutation({
    mutationFn: jobsApi.triggerBatchTag,
    onSuccess: (data) => {
      toast.success('Batch tagging started', {
        description: data.job_id ? `Job #${data.job_id}` : `${data.total} images`,
      });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start batch tagging'),
  });

  const triggerBatchDescribeMutation = useMutation({
    mutationFn: jobsApi.triggerBatchDescribe,
    onSuccess: (data) => {
      toast.success('Batch describing started', {
        description: data.job_id ? `Job #${data.job_id}` : `${data.total} images`,
      });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start batch describing'),
  });

  const triggerBatchEmbedMutation = useMutation({
    mutationFn: jobsApi.triggerBatchEmbed,
    onSuccess: (data) => {
      toast.success('Batch embedding started', {
        description: data.job_id ? `Job #${data.job_id}` : `${data.total} images`,
      });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start batch embedding'),
  });

  const triggerSummarizeAllMutation = useMutation({
    mutationFn: () => clustersApi.summarizeAll(),
    onSuccess: (data) => {
      toast.success('Cluster summarization started', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start summarization'),
  });

  const reprocessAllMutation = useMutation({
    mutationFn: jobsApi.reprocessAll,
    onSuccess: (data) => {
      toast.success('Reprocessing all images', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] });
    },
    onError: () => toast.error('Failed to start reprocessing'),
  });

  const reprocessFailedMutation = useMutation({
    mutationFn: jobsApi.reprocessFailed,
    onSuccess: (data) => {
      toast.success('Reprocessing failed images', { description: `Job #${data.job_id}` });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] });
    },
    onError: () => toast.error('Failed to start reprocessing'),
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

  const hasBatchRunning = jobs?.items.some(
    (j) => j.job_type === 'batch_reprocess' && (j.status === 'running' || j.status === 'pending')
  ) ?? false;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Jobs</h1>

        <div className="flex items-center gap-2">
          <button
            onClick={() => triggerBatchTagMutation.mutate()}
            disabled={triggerBatchTagMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <Tag className="h-4 w-4" />
            Tag All
          </button>

          <button
            onClick={() => triggerBatchDescribeMutation.mutate()}
            disabled={triggerBatchDescribeMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <FileText className="h-4 w-4" />
            Describe All
          </button>

          <button
            onClick={() => triggerBatchEmbedMutation.mutate()}
            disabled={triggerBatchEmbedMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <Cpu className="h-4 w-4" />
            Embed All
          </button>

          <div className="w-px h-6 bg-border" />

          <button
            onClick={() => reprocessAllMutation.mutate()}
            disabled={reprocessAllMutation.isPending || hasBatchRunning}
            title={hasBatchRunning ? 'A batch reprocess job is already running' : undefined}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <RefreshCw className={cn('h-4 w-4', reprocessAllMutation.isPending && 'animate-spin')} />
            Reprocess All
          </button>

          {stats && stats.failed > 0 && (
            <button
              onClick={() => reprocessFailedMutation.mutate()}
              disabled={reprocessFailedMutation.isPending || hasBatchRunning}
              title={hasBatchRunning ? 'A batch reprocess job is already running' : undefined}
              className={cn(
                'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                'border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/30',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <AlertTriangle className="h-4 w-4" />
              Reprocess Failed ({stats.failed})
            </button>
          )}

          <div className="w-px h-6 bg-border" />

          <button
            onClick={() => triggerClusteringMutation.mutate()}
            disabled={triggerClusteringMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <RefreshCw className={cn('h-4 w-4', triggerClusteringMutation.isPending && 'animate-spin')} />
            Recluster
          </button>

          <button
            onClick={() => triggerSummarizeAllMutation.mutate()}
            disabled={triggerSummarizeAllMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <Sparkles className="h-4 w-4" />
            Summarize All
          </button>

          <div className="w-px h-6 bg-border" />

          <button
            onClick={() => triggerPipelineMutation.mutate()}
            disabled={triggerPipelineMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <Play className="h-4 w-4" />
            Run Full Pipeline
          </button>
        </div>
      </div>

      {/* Pipeline Stats */}
      {stats && stats.total_images > 0 && (
        <div className="grid grid-cols-7 gap-3">
          {[
            { label: 'Ingested', count: stats.ingested, color: 'bg-gray-100 text-gray-700' },
            { label: 'Tagged', count: stats.tagged, color: 'bg-blue-100 text-blue-700' },
            { label: 'Described', count: stats.described, color: 'bg-indigo-100 text-indigo-700' },
            { label: 'Embedded', count: stats.embedded, color: 'bg-purple-100 text-purple-700' },
            { label: 'Clustered', count: stats.clustered, color: 'bg-green-100 text-green-700' },
            { label: 'Failed', count: stats.failed, color: 'bg-red-100 text-red-700' },
            { label: 'Total', count: stats.total_images, color: 'bg-muted text-foreground' },
          ].map(({ label, count, color }) => (
            <div key={label} className={cn('rounded-lg px-4 py-3 text-center', color)}>
              <div className="text-2xl font-bold">{count}</div>
              <div className="text-xs font-medium mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : jobs?.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-muted-foreground">No jobs yet</p>
          <p className="text-sm text-muted-foreground mt-1">
            Upload some images and run the pipeline to get started
          </p>
        </div>
      ) : (
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          <table className="w-full">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  ID
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Image
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Progress
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Model
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Cost
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Created
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {jobs?.items.map((job) => (
                <tr key={job.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3 text-sm font-mono">{job.id}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className="capitalize">{job.job_type.replace('_', ' ')}</span>
                    {job.job_type === 'lora_train' && job.parameters?.lora_model_id != null && (
                      <Link
                        href={`/models/${String(job.parameters.lora_model_id)}`}
                        className="ml-1.5 text-xs text-primary hover:underline"
                      >
                        Model #{String(job.parameters.lora_model_id)}
                      </Link>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {job.image_id ? (
                      <Link
                        href={`/images?image_id=${job.image_id}`}
                        className="flex items-center gap-2 hover:opacity-80 transition-opacity"
                      >
                        {job.image_thumbnail && (
                          <img
                            src={imagesApi.getThumbnailUrl(job.image_thumbnail)}
                            alt=""
                            className="h-8 w-8 rounded object-cover"
                          />
                        )}
                        <span className="truncate max-w-[120px] text-primary underline-offset-2 hover:underline">
                          {job.image_filename || `#${job.image_id}`}
                        </span>
                      </Link>
                    ) : job.job_type === 'batch_reprocess' ? (
                      <BatchImagesPill job={job} />
                    ) : (
                      <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                        Batch
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        'px-2 py-0.5 rounded-full text-xs font-medium',
                        getStatusColor(job.status)
                      )}
                    >
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <JobProgress job={job} />
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    <JobModel job={job} />
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <JobCost job={job} />
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {formatDate(job.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      {(job.status === 'pending' || job.status === 'running') && (
                        <button
                          onClick={() => cancelJobMutation.mutate(job.id)}
                          className="p-1.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg text-muted-foreground hover:text-red-600 transition-colors"
                          title="Cancel job"
                        >
                          <XCircle className="h-4 w-4" />
                        </button>
                      )}
                      {job.status === 'failed' && job.job_type !== 'lora_train' && (
                        <button
                          onClick={() => retryJobMutation.mutate(job.id)}
                          disabled={retryJobMutation.isPending}
                          className={cn(
                            'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
                            'border border-border text-foreground hover:bg-muted',
                            'disabled:opacity-50 disabled:cursor-not-allowed'
                          )}
                          title="Retry this job"
                        >
                          <RotateCcw className="h-3 w-3" />
                          Retry
                        </button>
                      )}
                      <LoraJobActions
                        job={job}
                        onRecover={(id) => recoverMutation.mutate(id)}
                        onRetry={(id) => retryMutation.mutate(id)}
                        isRecoverPending={recoverMutation.isPending}
                        isRetryPending={retryMutation.isPending}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Error display */}
      {jobs?.items.some((j) => j.error_message) && (
        <div className="space-y-2">
          <h2 className="font-semibold text-sm text-red-600">Recent Errors</h2>
          {jobs.items
            .filter((j) => j.error_message)
            .slice(0, 5)
            .map((job) => (
              <div
                key={job.id}
                className="bg-red-50 border border-red-200 dark:bg-red-900/30 dark:border-red-800 rounded-lg p-3 text-sm"
              >
                <p className="font-medium text-red-800 dark:text-red-300">
                  Job #{job.id} ({job.job_type})
                </p>
                <p className="text-red-700 dark:text-red-400 mt-1">{job.error_message}</p>
              </div>
            ))}
        </div>
      )}
    </div>
  );
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
              {images.slice(0, 10).map((img) => (
                <Link
                  key={img.id}
                  href={`/images?image_id=${img.id}`}
                  className="flex items-center gap-2 hover:bg-muted rounded p-1 transition-colors"
                >
                  {img.thumbnail ? (
                    <img
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
              {images.length > 10 && (
                <p className="text-xs text-muted-foreground text-center pt-1">
                  and {images.length - 10} more...
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-4">No images found</p>
          )}
        </div>
      )}
    </div>
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

const MODEL_DISPLAY_NAMES: Record<string, string> = {
  'flux-dev': 'Flux Dev',
  'qwen-2.5': 'Qwen 2.5',
  'fal-ai/nano-banana-pro': 'Nano Banana',
  'qwen-image-max-edit': 'Qwen Max Edit',
  'kling-image-o3': 'Kling O3',
  'wan-25-preview': 'Wan 2.5',
  'grok-imagine-edit': 'Grok Edit',
  'face-swap': 'Face Swap',
  'nano-banana-edit': 'Nano Banana Edit',
};

function JobModel({ job }: { job: Job }) {
  const params = job.parameters as Record<string, unknown> | null;
  const baseModel = params?.base_model as string | undefined;
  const editModel = params?.edit_model as string | undefined;
  const model = baseModel || editModel;

  if (!model) return <span className="text-xs text-muted-foreground">-</span>;

  const displayName = MODEL_DISPLAY_NAMES[model] || model;
  return (
    <span className="text-xs font-medium text-muted-foreground" title={model}>
      {displayName}
    </span>
  );
}

function JobCost({ job }: { job: Job }) {
  if (job.charged_cost == null) return <span className="text-xs text-muted-foreground">-</span>;

  // charged_cost is stored in sparks
  const sparks = Math.round(job.charged_cost);

  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-amber-600 dark:text-amber-400">
      <Zap className="h-3 w-3" />
      {sparks}
    </span>
  );
}

function JobProgress({ job }: { job: Job }) {
  const isIndividual = job.total_items <= 1;

  if (isIndividual) {
    if (job.status === 'completed') {
      return <Check className="h-4 w-4 text-green-600" />;
    }
    if (job.status === 'failed') {
      return <XCircle className="h-4 w-4 text-red-500" />;
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
            className="h-full bg-primary transition-all"
            style={{
              width: `${(job.progress / job.total_items) * 100}%`,
            }}
          />
        </div>
        <span className="text-xs text-muted-foreground">
          {job.progress}/{job.total_items}
        </span>
      </div>
    );
  }

  return <span className="text-muted-foreground">-</span>;
}
