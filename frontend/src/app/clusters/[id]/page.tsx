'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Pin,
  Archive,
  Download,
  Edit2,
  Check,
  X,
  Sparkles,
} from 'lucide-react';
import { clustersApi, imagesApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import { cn } from '@/lib/utils';
import type { Image } from '@/types';

export default function ClusterDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const clusterId = Number(params.id);

  const [selectedImage, setSelectedImage] = useState<Image | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState('');

  const { data: cluster, isLoading } = useQuery({
    queryKey: ['cluster', clusterId],
    queryFn: () => clustersApi.get(clusterId),
  });

  const renameMutation = useMutation({
    mutationFn: (name: string) => clustersApi.rename(clusterId, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cluster', clusterId] });
      setIsEditing(false);
    },
  });

  const pinMutation = useMutation({
    mutationFn: () => clustersApi.togglePin(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cluster', clusterId] });
      queryClient.invalidateQueries({ queryKey: ['clusters'] });
    },
  });

  const summarizeMutation = useMutation({
    mutationFn: () => clustersApi.summarize(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cluster', clusterId] });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () => clustersApi.archive(clusterId),
    onSuccess: () => {
      router.push('/');
    },
  });

  if (isLoading || !cluster) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  const title = cluster.display_name || cluster.summary_title || `Cluster ${cluster.id}`;

  const handleStartEdit = () => {
    setEditName(title);
    setIsEditing(true);
  };

  const handleSaveEdit = () => {
    if (editName.trim()) {
      renameMutation.mutate(editName.trim());
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <button
            onClick={() => router.back()}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>

          <div>
            {isEditing ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="text-2xl font-bold px-2 py-1 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20"
                  autoFocus
                />
                <button
                  onClick={handleSaveEdit}
                  className="p-1.5 hover:bg-green-100 rounded-lg text-green-600"
                >
                  <Check className="h-5 w-5" />
                </button>
                <button
                  onClick={() => setIsEditing(false)}
                  className="p-1.5 hover:bg-red-100 rounded-lg text-red-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold">{title}</h1>
                <button
                  onClick={handleStartEdit}
                  className="p-1.5 hover:bg-muted rounded-lg text-muted-foreground"
                >
                  <Edit2 className="h-4 w-4" />
                </button>
              </div>
            )}
            <p className="text-muted-foreground mt-1">
              {cluster.size} images • {cluster.method}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => summarizeMutation.mutate()}
            disabled={summarizeMutation.isPending}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
              'border border-border hover:bg-muted'
            )}
          >
            <Sparkles className={cn('h-4 w-4', summarizeMutation.isPending && 'animate-pulse')} />
            Regenerate Summary
          </button>

          <button
            onClick={() => pinMutation.mutate()}
            className={cn(
              'p-2 rounded-lg transition-colors',
              cluster.is_pinned
                ? 'bg-primary text-primary-foreground'
                : 'border border-border hover:bg-muted'
            )}
          >
            <Pin className="h-4 w-4" />
          </button>

          <a
            href={clustersApi.exportCluster(clusterId, 'zip')}
            className="p-2 border border-border rounded-lg hover:bg-muted transition-colors"
          >
            <Download className="h-4 w-4" />
          </a>

          <button
            onClick={() => archiveMutation.mutate()}
            className="p-2 border border-border rounded-lg hover:bg-red-50 hover:border-red-200 text-muted-foreground hover:text-red-600 transition-colors"
          >
            <Archive className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Summary */}
      {cluster.summary_description && (
        <div className="bg-muted/50 rounded-xl p-4">
          <h3 className="font-medium text-sm mb-2">Summary</h3>
          <div className="text-sm text-muted-foreground whitespace-pre-line">
            {cluster.summary_description}
          </div>
        </div>
      )}

      {/* Common Tags */}
      {Object.keys(cluster.common_tags).length > 0 && (
        <div>
          <h3 className="font-medium text-sm mb-3">Common Tags</h3>
          <div className="flex flex-wrap gap-4">
            {Object.entries(cluster.common_tags).map(([category, tags]) =>
              tags.length > 0 ? (
                <div key={category}>
                  <span className="text-xs text-muted-foreground capitalize">
                    {category.replace('_', ' ')}:
                  </span>
                  <div className="flex gap-1 mt-1">
                    {tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 bg-muted rounded-full text-xs"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null
            )}
          </div>
        </div>
      )}

      {/* Images Grid */}
      <div>
        <h3 className="font-medium text-sm mb-3">Images</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {cluster.images.map((image) => (
            <ImageCard
              key={image.id}
              image={image}
              onClick={() => setSelectedImage(image)}
            />
          ))}
        </div>
      </div>

      {/* Image Drawer */}
      {selectedImage && (
        <ImageDrawer
          image={selectedImage}
          onClose={() => setSelectedImage(null)}
        />
      )}
    </div>
  );
}
