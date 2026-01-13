'use client';

import { useQuery } from '@tanstack/react-query';
import { clustersApi, imagesApi } from '@/lib/api';
import ClusterCard from '@/components/ClusterCard';
import { Loader2 } from 'lucide-react';

export default function HomePage() {
  const { data: clusters, isLoading, error } = useQuery({
    queryKey: ['clusters'],
    queryFn: () => clustersApi.list({ limit: 100 }),
  });

  if (isLoading) {
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

  if (!clusters?.items.length) {
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
  const pinnedClusters = clusters.items.filter((c) => c.is_pinned);
  const regularClusters = clusters.items.filter((c) => !c.is_pinned);

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
    </div>
  );
}
