'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { foldersApi } from '@/lib/api';

interface AddToFolderDialogProps {
  imageIds: number[];
  onClose: () => void;
  onDone: () => void;
}

export default function AddToFolderDialog({
  imageIds,
  onClose,
  onDone,
}: AddToFolderDialogProps) {
  const queryClient = useQueryClient();
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const { data: folders } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
  });

  const addMutation = useMutation({
    mutationFn: async () => {
      let folderId = selectedFolderId;
      if (isCreating && newFolderName.trim()) {
        const folder = await foldersApi.create({ name: newFolderName.trim() });
        folderId = folder.id;
      }
      if (!folderId) throw new Error('No folder selected');
      return foldersApi.addImages(folderId, imageIds);
    },
    onSuccess: (data) => {
      toast.success(`Added ${data.added} images to folder`);
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      onDone();
    },
    onError: () => {
      toast.error('Failed to add images to folder');
    },
  });

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="bg-card rounded-xl shadow-xl max-w-md w-full p-6 space-y-4"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className="text-lg font-semibold">Add to Folder</h3>
          <p className="text-sm text-muted-foreground">
            Add {imageIds.length} image{imageIds.length !== 1 ? 's' : ''} to a folder
          </p>

          {!isCreating ? (
            <div className="space-y-3">
              <select
                className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                value={selectedFolderId ?? ''}
                onChange={(e) => setSelectedFolderId(Number(e.target.value) || null)}
              >
                <option value="">Select a folder...</option>
                {folders?.items.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.image_count} images)
                  </option>
                ))}
              </select>
              <button
                onClick={() => setIsCreating(true)}
                className="text-sm text-primary hover:underline"
              >
                + Create new folder
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <input
                type="text"
                placeholder="New folder name"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                autoFocus
              />
              <button
                onClick={() => {
                  setIsCreating(false);
                  setNewFolderName('');
                }}
                className="text-sm text-muted-foreground hover:underline"
              >
                Back to existing folders
              </button>
            </div>
          )}

          <div className="flex gap-2 justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => addMutation.mutate()}
              disabled={
                addMutation.isPending ||
                (!isCreating && !selectedFolderId) ||
                (isCreating && !newFolderName.trim())
              }
              className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {addMutation.isPending ? 'Adding...' : 'Add'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
