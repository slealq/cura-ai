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
  CheckSquare,
  FolderPlus,
} from 'lucide-react';
import { toast } from 'sonner';
import { clustersApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import AddToFolderDialog from '@/components/AddToFolderDialog';
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

  // Selection state
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [showAddToFolder, setShowAddToFolder] = useState(false);
  const [addToFolderIds, setAddToFolderIds] = useState<number[]>([]);

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

  const handleToggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    const allIds = cluster.images.map((img) => img.id);
    const allSelected = allIds.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(allIds));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  const openAddToFolderSelected = () => {
    setAddToFolderIds(Array.from(selectedIds));
    setShowAddToFolder(true);
  };

  const openAddToFolderAll = () => {
    setAddToFolderIds(cluster.images.map((img) => img.id));
    setShowAddToFolder(true);
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
          {/* Create Folder from All */}
          <button
            onClick={openAddToFolderAll}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
              'border border-border hover:bg-muted'
            )}
          >
            <FolderPlus className="h-4 w-4" />
            Create Folder from All
          </button>

          {/* Select mode toggle */}
          {selectMode ? (
            <>
              <button
                onClick={handleSelectAll}
                className={cn(
                  'px-3 py-2 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted'
                )}
              >
                {cluster.images.every((img) => selectedIds.has(img.id))
                  ? 'Deselect All'
                  : 'Select All'}
              </button>
              <button
                onClick={exitSelectMode}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted'
                )}
              >
                <X className="h-3.5 w-3.5" />
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setSelectMode(true)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors',
                'border border-border hover:bg-muted'
              )}
            >
              <CheckSquare className="h-3.5 w-3.5" />
              Select
            </button>
          )}

          <div className="w-px h-6 bg-border" />

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
      {cluster.common_tags.length > 0 && (
        <div>
          <h3 className="font-medium text-sm mb-3">Common Tags</h3>
          <div className="flex flex-wrap gap-1">
            {cluster.common_tags.map((tag) => (
              <span
                key={tag}
                className="px-2 py-0.5 bg-muted rounded-full text-xs"
              >
                {tag}
              </span>
            ))}
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
              onClick={selectMode ? undefined : () => setSelectedImage(image)}
              selectable={selectMode}
              selected={selectedIds.has(image.id)}
              onSelect={handleToggleSelect}
            />
          ))}
        </div>
      </div>

      {/* Floating action bar for selection */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-white border border-border rounded-xl shadow-lg px-4 py-3 flex items-center gap-3 z-50">
          <span className="text-sm font-medium">
            {selectedIds.size} image{selectedIds.size !== 1 ? 's' : ''} selected
          </span>
          <button
            onClick={openAddToFolderSelected}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90'
            )}
          >
            <FolderPlus className="h-3.5 w-3.5" />
            Create Folder from Selected
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="p-1.5 hover:bg-muted rounded-lg text-muted-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Add to Folder dialog */}
      {showAddToFolder && (
        <AddToFolderDialog
          imageIds={addToFolderIds}
          onClose={() => setShowAddToFolder(false)}
          onDone={() => {
            setShowAddToFolder(false);
            setSelectedIds(new Set());
            setSelectMode(false);
            toast.success('Images added to folder');
          }}
        />
      )}

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
