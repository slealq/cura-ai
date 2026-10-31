'use client';

import Link from 'next/link';
import { useParams, usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { clustersApi } from '@/lib/api';
import { useRouteParam } from '@/lib/utils';
import ImageGrid from '@/components/ImageGrid';
import ClusterTools, { clusterTitle, clusterBullets } from '@/components/ClusterTools';

export default function ClusterDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const id = useRouteParam(params.id as string, 1, pathname);
  const { data: cluster, isLoading, isError, refetch } = useQuery({
    queryKey: ['cluster', id], queryFn: () => clustersApi.get(id), enabled: Number.isFinite(id),
    refetchInterval: query => query.state.data && !query.state.data.summary_title ? 5000 : false,
  });
  if (isError) return <div role="alert" className="py-12 text-sm text-muted-foreground">Failed to load cluster. <button onClick={() => refetch()} className="underline">Retry</button> · <Link href="/clusters">Back to clusters</Link></div>;
  if (isLoading || !cluster) return <div className="grid h-64 place-items-center"><div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" /></div>;
  return <div className="min-w-0 space-y-3">
    <Link href="/clusters" className="text-sm text-muted-foreground hover:text-foreground">← Clusters</Link>
    <ImageGrid
      title={clusterTitle(cluster)}
      queryKeyPrefix={`cluster-images-${id}-${cluster.updated_at}-${cluster.size}`}
      clusterId={id}
      fetchImages={async ({ skip = 0, limit = 60, status, min_status, max_status }) => {
        const statuses = ['pending', 'ingested', 'normalized', 'tagged', 'described', 'embedded', 'clustered'];
        const images = cluster.images.filter(image => (!status || image.status === status)
          && (!min_status || statuses.indexOf(image.status) >= statuses.indexOf(min_status))
          && (!max_status || (statuses.indexOf(image.status) >= 0 && statuses.indexOf(image.status) <= statuses.indexOf(max_status))));
        return { items: images.slice(skip, skip + limit), total: images.length, skip, limit };
      }}
      subtitle={<div className="space-y-2">
        <p className="font-mono text-xs text-muted-foreground">{cluster.size.toLocaleString()} images · {cluster.method}{cluster.is_pinned ? ' · Pinned' : ''}</p>
        {cluster.summary_description ? <ul className="max-w-[68ch] list-disc space-y-1 pl-4 text-sm text-muted-foreground">{clusterBullets(cluster).slice(0, 3).map((bullet, index) => <li key={index}>{bullet}</li>)}</ul> : <p className="text-sm text-muted-foreground">Summarizing cluster…</p>}
        <div className="flex flex-wrap gap-1">{cluster.common_tags.map(tag => <span key={tag} className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">{tag}</span>)}</div>
      </div>}
      inspectorOverview={<><p className="text-muted-foreground">{cluster.size.toLocaleString()} images in this cluster</p><ClusterTools clusters={[cluster]} detail /></>}
    />
  </div>;
}
