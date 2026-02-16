'use client';

import { useState, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { clustersApi } from '@/lib/api';
import ClusterCard from '@/components/ClusterCard';
import { Loader2 } from 'lucide-react';
import type { Cluster } from '@/types';

const PAGE_SIZE = 20;

export default function HomePage() {
  const [allItems, setAllItems] = useState<Cluster[]>([]);
  const [page, setPage] = useState(0);

  const { data, isLoading, error } = useQuery({
    queryKey: ['clusters', page],
    queryFn: () => clustersApi.list({ skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
  });

  useEffect(() => {
    if (data) {
      setAllItems((prev) => {
        const updated = prev.slice(0, page * PAGE_SIZE);
        return [...updated, ...data.items];
      });
    }
  }, [data, page]);

  const total = data?.total ?? 0;
  const hasMore = allItems.length < total;

  const loadMore = useCallback(() => {
    setPage((p) => p + 1);
  }, []);

  if (isLoading && page === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Failed to load clusters</p>
      </div>
    );
  }

  if (allItems.length === 0 && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <p className="text-muted-foreground mb-2">No clusters yet</p>
        <p className="text-sm text-muted-foreground">
          Upload some images and run clustering to get started
        </p>
      </div>
    );
  }

  // Separate pinned and regular clusters
  const pinnedClusters = allItems.filter((c) => c.is_pinned);
  const regularClusters = allItems.filter((c) => !c.is_pinned);

  return (
    <div className="space-y-8">
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
    </div>
  );
}
