'use client';

import { useState } from 'react';
import { useParams, useRouter, usePathname } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, ArrowLeft, Pencil, Trash2, Box } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { foldersApi } from '@/lib/api';
import ImageGrid from '@/components/ImageGrid';
import { cn, useRouteParam } from '@/lib/utils';
import type { Folder, FolderListResponse } from '@/types';

export default function FolderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const folderId = useRouteParam(params.id as string, 2, pathname);

  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteWithImages, setDeleteWithImages] = useState(false);

  const { data: folder, isLoading } = useQuery({
    queryKey: ['folders', folderId],
    queryFn: () => foldersApi.get(folderId),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      foldersApi.update(folderId, {
        name: editName.trim() || undefined,
        description: editDescription.trim(),
      }),
    onSuccess: () => {
      toast.success('Folder updated');
      queryClient.invalidateQueries({ queryKey: ['folders', folderId] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      setIsEditing(false);
    },
    onError: () => {
      toast.error('Failed to update folder');
    },
  });

  const deleteSimpleMutation = useMutation({
    mutationFn: () => foldersApi.delete(folderId, false),
    onSuccess: () => {
      toast.success('Folder deleted');
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      router.push('/images');
    },
    onError: () => {
      toast.error('Failed to delete folder');
    },
  });

  const handleDeleteWithImages = () => {
    // Immediate feedback — don't wait for API response
    const toastId = `delete-folder-${folderId}`;
    toast.loading(`Deleting "${folder?.name}" and all images...`, { id: toastId });

    // Mark folder as deleting in sessionStorage (survives refreshes, no race conditions)
    const raw = sessionStorage.getItem('deleting-folders');
    const ids: number[] = raw ? JSON.parse(raw) : [];
    if (!ids.includes(folderId)) ids.push(folderId);
    sessionStorage.setItem('deleting-folders', JSON.stringify(ids));

    // Optimistically remove from folders cache
    queryClient.setQueryData<FolderListResponse>(['folders'], (old) => {
      if (!old) return old;
      return { ...old, items: old.items.filter((f) => f.id !== folderId), total: old.total - 1 };
    });

    router.push('/images');

    foldersApi.delete(folderId, true).then((data) => {
      if (data.job_id) {
        toast.success(data.message || 'Deleting folder and images', {
          id: toastId,
          action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
          duration: 5000,
        });
      }
      // Only refresh jobs — folders will be refreshed by useJobNotifications
      // when the delete job actually completes (folder gone from DB)
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    }).catch(() => {
      toast.error('Failed to delete folder', { id: toastId });
      // Refetch folders on error since the optimistic removal was wrong
      queryClient.invalidateQueries({ queryKey: ['folders'] });
    });
  };

  if (isLoading || !folder) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const startEditing = () => {
    setEditName(folder.name);
    setEditDescription(folder.description || '');
    setIsEditing(true);
  };

  return (
    <div className="space-y-4">
      {/* Breadcrumb + folder info */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/images" className="hover:text-foreground transition-colors">
          Images
        </Link>
        <span>/</span>
        <span className="text-foreground">{folder.name}</span>
      </div>

      {/* Folder header */}
      {isEditing ? (
        <div className="space-y-3 p-4 border border-border rounded-lg bg-muted/30">
          <input
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            className="w-full px-3 py-2 border border-border rounded-lg text-sm font-semibold"
            autoFocus
          />
          <textarea
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[60px]"
          />
          <div className="flex gap-2">
            <button
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending || !editName.trim()}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => setIsEditing(false)}
              className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between">
          <div>
            {folder.description && (
              <p className="text-sm text-muted-foreground mt-1">{folder.description}</p>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Link
              href={`/models?train_folder=${folderId}`}
              className="p-2 hover:bg-purple-50 dark:hover:bg-purple-900/30 rounded-lg transition-colors text-muted-foreground hover:text-purple-600 dark:hover:text-purple-400"
              title="Train LoRA from this folder"
            >
              <Box className="h-4 w-4" />
            </Link>
            <button
              onClick={startEditing}
              className="p-2 hover:bg-muted rounded-lg transition-colors text-muted-foreground"
              title="Edit folder"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="p-2 hover:bg-red-50 rounded-lg transition-colors text-muted-foreground hover:text-red-600"
              title="Delete folder"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Image Grid */}
      <ImageGrid
        title={folder.name}
        queryKeyPrefix={`folder-${folderId}-images`}
        fetchImages={(params) => foldersApi.listImages(folderId, params)}
        folderId={folderId}
      />

      {/* Delete Confirmation */}
      {showDeleteConfirm && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => { setShowDeleteConfirm(false); setDeleteWithImages(false); }}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-sm w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Delete Folder</h3>
              <p className="text-sm text-muted-foreground">
                Delete &ldquo;{folder.name}&rdquo;?
              </p>

              <div className="space-y-2">
                <label
                  className={cn(
                    'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                    !deleteWithImages
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:bg-muted/50'
                  )}
                >
                  <input
                    type="radio"
                    name="deleteOption"
                    checked={!deleteWithImages}
                    onChange={() => setDeleteWithImages(false)}
                    className="mt-0.5"
                  />
                  <div>
                    <div className="text-sm font-medium">Delete folder only</div>
                    <div className="text-xs text-muted-foreground">Images will be kept</div>
                  </div>
                </label>

                <label
                  className={cn(
                    'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                    deleteWithImages
                      ? 'border-red-500 bg-red-50 dark:bg-red-950/30'
                      : 'border-border hover:bg-muted/50'
                  )}
                >
                  <input
                    type="radio"
                    name="deleteOption"
                    checked={deleteWithImages}
                    onChange={() => setDeleteWithImages(true)}
                    className="mt-0.5"
                  />
                  <div>
                    <div className={cn('text-sm font-medium', deleteWithImages && 'text-red-600 dark:text-red-400')}>
                      Delete folder and all {folder.image_count} image{folder.image_count !== 1 ? 's' : ''}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Permanently deletes images, including from other folders
                    </div>
                  </div>
                </label>
              </div>

              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setShowDeleteConfirm(false); setDeleteWithImages(false); }}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    if (deleteWithImages) {
                      handleDeleteWithImages();
                    } else {
                      deleteSimpleMutation.mutate();
                    }
                    setDeleteWithImages(false);
                  }}
                  disabled={deleteSimpleMutation.isPending}
                  className={cn(
                    'px-4 py-2 text-sm text-white rounded-lg transition-colors disabled:opacity-50',
                    deleteWithImages
                      ? 'bg-red-600 hover:bg-red-700'
                      : 'bg-primary hover:bg-primary/90'
                  )}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
