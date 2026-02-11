'use client';

import Link from 'next/link';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, XCircle, RefreshCw, Tag, FileText, Cpu, Sparkles, Check } from 'lucide-react';
import { jobsApi, clustersApi, imagesApi } from '@/lib/api';
import { cn, formatDate, getStatusColor } from '@/lib/utils';
import type { Job } from '@/types';

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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const triggerClusteringMutation = useMutation({
    mutationFn: () => clustersApi.recluster(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const triggerBatchTagMutation = useMutation({
    mutationFn: jobsApi.triggerBatchTag,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const triggerBatchDescribeMutation = useMutation({
    mutationFn: jobsApi.triggerBatchDescribe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const triggerBatchEmbedMutation = useMutation({
    mutationFn: jobsApi.triggerBatchEmbed,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const triggerSummarizeAllMutation = useMutation({
    mutationFn: () => clustersApi.summarizeAll(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const cancelJobMutation = useMutation({
    mutationFn: jobsApi.cancel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

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
        <div className="bg-white rounded-xl border border-border overflow-hidden">
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
                  <td className="px-4 py-3 text-sm capitalize">
                    {job.job_type.replace('_', ' ')}
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
                    {formatDate(job.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    {(job.status === 'pending' || job.status === 'running') && (
                      <button
                        onClick={() => cancelJobMutation.mutate(job.id)}
                        className="p-1.5 hover:bg-red-100 rounded-lg text-muted-foreground hover:text-red-600 transition-colors"
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                    )}
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
                className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm"
              >
                <p className="font-medium text-red-800">
                  Job #{job.id} ({job.job_type})
                </p>
                <p className="text-red-700 mt-1">{job.error_message}</p>
              </div>
            ))}
        </div>
      )}
    </div>
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
