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

  const deleteMutation = useMutation({
    mutationFn: () => foldersApi.delete(folderId),
    onSuccess: () => {
      toast.success('Folder deleted');
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      router.push('/images');
    },
    onError: () => {
      toast.error('Failed to delete folder');
    },
  });

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
          Folders
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
            onClick={() => setShowDeleteConfirm(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-sm w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Delete Folder</h3>
              <p className="text-sm text-muted-foreground">
                Delete &ldquo;{folder.name}&rdquo;? Images will not be deleted.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                >
                  {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
