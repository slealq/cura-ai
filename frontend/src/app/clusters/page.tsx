'use client';

import { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { clustersApi, jobsApi } from '@/lib/api';
import ClusterCard from '@/components/ClusterCard';
import { Loader2, Play, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import type { Cluster } from '@/types';

const PAGE_SIZE = 20;

function clusterIsComplete(c: Cluster): boolean {
  return c.summary_title !== null && c.summary_title !== '';
}

export default function ClustersPage() {
  const queryClient = useQueryClient();
  const [allItems, setAllItems] = useState<Cluster[]>([]);
  const [page, setPage] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isReclustering, setIsReclustering] = useState(false);
  const [reclusterJobId, setReclusterJobId] = useState<number | null>(null);

  // Check if any loaded cluster is still waiting for summarization
  const hasPendingSummaries = allItems.length > 0 && allItems.some((c) => !clusterIsComplete(c));

  const { data, isLoading, error } = useQuery({
    queryKey: ['clusters', page],
    queryFn: () => clustersApi.list({ skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
    enabled: !isReclustering,
    // Keep polling while clusters are missing summaries
    refetchInterval: hasPendingSummaries ? 5000 : false,
  });

  // Poll for clustering job completion
  useQuery({
    queryKey: ['cluster-job', reclusterJobId],
    queryFn: () => jobsApi.get(reclusterJobId!),
    refetchInterval: 3000,
    enabled: reclusterJobId !== null,
    select: (job) => {
      if (job.status === 'completed') {
        setIsReclustering(false);
        setReclusterJobId(null);
        setAllItems([]);
        setPage(0);
        queryClient.invalidateQueries({ queryKey: ['clusters'] });
        toast.success('Clustering completed — summarizing clusters...');
      } else if (job.status === 'failed') {
        setIsReclustering(false);
        setReclusterJobId(null);
        setAllItems([]);
        setPage(0);
        queryClient.invalidateQueries({ queryKey: ['clusters'] });
        toast.error('Clustering failed', {
          description: job.error_message || `Job #${job.id}`,
        });
      }
      return job;
    },
  });

  useEffect(() => {
    if (data) {
      setAllItems((prev) => {
        const updated = prev.slice(0, page * PAGE_SIZE);
        return [...updated, ...data.items];
      });
    }
  }, [data, page]);

  const clusterMutation = useMutation({
    mutationFn: () => clustersApi.recluster(),
    onSuccess: (result) => {
      setIsReclustering(true);
      setReclusterJobId(result.job_id);
      setAllItems([]);
      toast.success('Clustering job started', {
        action: { label: 'View Jobs', onClick: () => window.location.href = '/jobs' },
      });
    },
    onError: () => {
      toast.error('Failed to start clustering');
    },
  });

  const handleRunClustering = () => {
    if (allItems.length > 0) {
      setShowConfirm(true);
    } else {
      clusterMutation.mutate();
    }
  };

  const confirmRecluster = () => {
    setShowConfirm(false);
    clusterMutation.mutate();
  };

  const total = data?.total ?? 0;
  const hasMore = allItems.length < total;

  const loadMore = useCallback(() => {
    setPage((p) => p + 1);
  }, []);

  // Only show clusters that have been fully summarized
  const readyItems = allItems.filter(clusterIsComplete);

  // Separate pinned and regular clusters
  const pinnedClusters = readyItems.filter((c) => c.is_pinned);
  const regularClusters = readyItems.filter((c) => !c.is_pinned);

  const header = (
    <div className="flex items-center justify-between">
      <h1 className="text-2xl font-bold">Clusters</h1>
      <button
        onClick={handleRunClustering}
        disabled={clusterMutation.isPending || isReclustering}
        className={cn(
          'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          'bg-primary text-primary-foreground hover:bg-primary/90',
          'disabled:opacity-50 disabled:cursor-not-allowed'
        )}
      >
        {clusterMutation.isPending || isReclustering ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        Run Clustering
      </button>
    </div>
  );

  if (isReclustering) {
    return (
      <div className="space-y-8">
        {header}
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-4" />
          <p className="text-muted-foreground">Clustering in progress...</p>
          <p className="text-sm text-muted-foreground mt-1">
            New clusters will appear automatically when complete
          </p>
        </div>
      </div>
    );
  }

  if (isLoading && page === 0) {
    return (
      <div className="space-y-8">
        {header}
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-8">
        {header}
        <div className="flex items-center justify-center h-64">
          <p className="text-muted-foreground">Failed to load clusters</p>
        </div>
      </div>
    );
  }

  if (allItems.length === 0 && !isLoading) {
    return (
      <div className="space-y-8">
        {header}
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-muted-foreground mb-2">No clusters yet</p>
          <p className="text-sm text-muted-foreground">
            Upload some images and run clustering to get started
          </p>
        </div>
      </div>
    );
  }

  if (readyItems.length === 0 && hasPendingSummaries) {
    return (
      <div className="space-y-8">
        {header}
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-4" />
          <p className="text-muted-foreground">Summarizing clusters...</p>
          <p className="text-sm text-muted-foreground mt-1">
            Clusters will appear as summaries complete ({allItems.length - readyItems.length} remaining)
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {header}

      {pinnedClusters.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Pinned Clusters</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {pinnedClusters.map((cluster) => (
              <ClusterCard key={cluster.id} cluster={cluster} />
            ))}
          </div>
        </section>
      )}

      {hasPendingSummaries && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted/50 rounded-lg px-4 py-3">
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          Summarizing clusters... ({allItems.length - readyItems.length} remaining)
        </div>
      )}

      <section>
        <h2 className="text-lg font-semibold mb-4">
          All Clusters ({regularClusters.length})
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {regularClusters.map((cluster) => (
            <ClusterCard key={cluster.id} cluster={cluster} />
          ))}
        </div>
      </section>

      {hasMore && (
        <div className="flex justify-center pt-2">
          <button
            onClick={loadMore}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Load More ({total - allItems.length} remaining)
          </button>
        </div>
      )}

      {/* Recluster Confirmation Dialog */}
      {showConfirm && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowConfirm(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-sm w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
                <div>
                  <h3 className="font-semibold text-card-foreground">Replace existing clusters?</h3>
                  <p className="text-sm text-muted-foreground mt-1">
                    Running clustering will delete all existing clusters. Save important clusters as folders first.
                  </p>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowConfirm(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmRecluster}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                >
                  Run Clustering
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
