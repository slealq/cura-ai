'use client';

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { Loader2, Plus, Image as ImageIcon } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { foldersApi } from '@/lib/api';
import FolderCard from '@/components/FolderCard';
import { cn } from '@/lib/utils';

export default function FoldersPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [newFolderDescription, setNewFolderDescription] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
  });

  // Hide folders that are being deleted — read from sessionStorage (instant, no race)
  const visibleFolders = useMemo(() => {
    if (!data?.items) return [];
    const raw = sessionStorage.getItem('deleting-folders');
    if (!raw) return data.items;
    const deletingIds = new Set<number>(JSON.parse(raw) as number[]);
    if (deletingIds.size === 0) return data.items;
    return data.items.filter((f) => !deletingIds.has(f.id));
  }, [data]);

  const createMutation = useMutation({
    mutationFn: () =>
      foldersApi.create({
        name: newFolderName.trim(),
        description: newFolderDescription.trim() || undefined,
      }),
    onSuccess: (folder) => {
      toast.success(`Folder "${folder.name}" created`);
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      setShowCreateDialog(false);
      setNewFolderName('');
      setNewFolderDescription('');
      router.push(`/images/folder/${folder.id}`);
    },
    onError: () => {
      toast.error('Failed to create folder');
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Folders</h1>
        <div className="flex items-center gap-2">
          <Link
            href="/images/all"
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
              'border border-border hover:bg-muted'
            )}
          >
            <ImageIcon className="h-3.5 w-3.5" />
            All Images
          </Link>
          <button
            onClick={() => setShowCreateDialog(true)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90'
            )}
          >
            <Plus className="h-3.5 w-3.5" />
            New Folder
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : visibleFolders.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-muted-foreground">No folders yet</p>
          <p className="text-sm text-muted-foreground mt-1">
            Create a folder to organize your images
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {visibleFolders.map((folder) => (
            <FolderCard key={folder.id} folder={folder} />
          ))}
        </div>
      )}

      {/* Create Folder Dialog */}
      {showCreateDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowCreateDialog(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-md w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Create Folder</h3>
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  placeholder="e.g. LindaBooxo"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newFolderName.trim()) {
                      createMutation.mutate();
                    }
                  }}
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">
                  Description <span className="text-muted-foreground">(optional)</span>
                </label>
                <textarea
                  placeholder="What kind of images go here?"
                  value={newFolderDescription}
                  onChange={(e) => setNewFolderDescription(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowCreateDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createMutation.mutate()}
                  disabled={createMutation.isPending || !newFolderName.trim()}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Creating...' : 'Create'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
