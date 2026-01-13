'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, XCircle, RefreshCw } from 'lucide-react';
import { jobsApi, clustersApi } from '@/lib/api';
import { cn, formatDate, getStatusColor } from '@/lib/utils';

export default function JobsPage() {
  const queryClient = useQueryClient();

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
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

          <button
            onClick={() => triggerClusteringMutation.mutate()}
            disabled={triggerClusteringMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-border hover:bg-muted',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <RefreshCw className={cn('h-4 w-4', triggerClusteringMutation.isPending && 'animate-spin')} />
            Recluster
          </button>
        </div>
      </div>

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
                    {job.total_items > 0 ? (
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
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
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
