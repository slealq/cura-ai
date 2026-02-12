'use client';

import Link from 'next/link';
import { Pin, Image as ImageIcon } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import type { Cluster, Image } from '@/types';
import { imagesApi, clustersApi } from '@/lib/api';
import { cn } from '@/lib/utils';

interface ClusterCardProps {
  cluster: Cluster;
}

export default function ClusterCard({ cluster }: ClusterCardProps) {
  // Fetch representative images from the cluster images endpoint
  const { data: images } = useQuery({
    queryKey: ['cluster-images', cluster.id, 'preview'],
    queryFn: () => clustersApi.getImages(cluster.id, { limit: 6 }),
    enabled: cluster.size > 0,
  });

  const title = cluster.display_name || cluster.summary_title || `Cluster ${cluster.id}`;
  const topTags = cluster.common_tags.slice(0, 6);

  return (
    <Link href={`/clusters/${cluster.id}`}>
      <div className="group bg-white rounded-xl border border-border overflow-hidden hover:shadow-lg transition-shadow">
        {/* Thumbnail Grid */}
        <div className="aspect-video bg-muted relative">
          {images && images.length > 0 ? (
            <div className="grid grid-cols-3 grid-rows-2 h-full">
              {images.slice(0, 6).map((img, i) => (
                <div
                  key={img.id}
                  className={cn(
                    'relative overflow-hidden',
                    i === 0 && 'col-span-2 row-span-2'
                  )}
                >
                  <img
                    src={
                      img.thumbnail_uri_medium
                        ? imagesApi.getThumbnailUrl(img.thumbnail_uri_medium.split('/').pop()!)
                        : '/placeholder.png'
                    }
                    alt=""
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full">
              <ImageIcon className="h-12 w-12 text-muted-foreground/50" />
            </div>
          )}

          {/* Pinned indicator */}
          {cluster.is_pinned && (
            <div className="absolute top-2 right-2 p-1.5 bg-white/90 rounded-full">
              <Pin className="h-4 w-4 text-primary" />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="p-4">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-medium text-sm line-clamp-2">{title}</h3>
            <span className="text-xs text-muted-foreground shrink-0">
              {cluster.size} images
            </span>
          </div>

          {cluster.summary_description && (
            <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
              {cluster.summary_description.replace(/^- /gm, '').replace(/\n/g, ' ')}
            </p>
          )}

          {topTags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {topTags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 bg-muted rounded-full text-xs text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
