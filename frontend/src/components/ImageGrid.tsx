'use client';

import { Suspense, useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useRouter } from 'next/navigation';
import { Loader2, CheckSquare, X, RefreshCw, FolderPlus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { imagesApi, jobsApi, foldersApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import AddToFolderDialog from '@/components/AddToFolderDialog';
import { cn } from '@/lib/utils';
import type { Image, ImageListResponse } from '@/types';

type FilterMode = 'none' | 'min_status' | 'exact';

const statusFilters: { value: string | undefined; label: string; mode: FilterMode }[] = [
  { value: undefined, label: 'All', mode: 'none' },
  { value: 'ingested', label: 'Ingested', mode: 'exact' },
  { value: 'tagged', label: 'Tagged', mode: 'exact' },
  { value: 'described', label: 'Described', mode: 'exact' },
  { value: 'embedded', label: 'Embedded', mode: 'exact' },
  { value: 'clustered', label: 'Clustered', mode: 'exact' },
  { value: 'failed', label: 'Failed', mode: 'exact' },
];

interface ImageGridProps {
  title: string;
  queryKeyPrefix: string;
  fetchImages: (params: {
    status?: string;
    min_status?: string;
    skip?: number;
    limit?: number;
  }) => Promise<ImageListResponse>;
  folderId?: number;
}

export default function ImageGrid({ title, queryKeyPrefix, fetchImages, folderId }: ImageGridProps) {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <ImageGridContent
        title={title}
        queryKeyPrefix={queryKeyPrefix}
        fetchImages={fetchImages}
        folderId={folderId}
      />
    </Suspense>
  );
}

function ImageGridContent({ title, queryKeyPrefix, fetchImages, folderId }: ImageGridProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const imageIdParam = searchParams.get('image_id');
  const [selectedImage, setSelectedImage] = useState<Image | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [filterMode, setFilterMode] = useState<FilterMode>('none');
  const [page, setPage] = useState(0);
  const limit = 50;

  // Multi-select state
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // Add to folder dialog
  const [showAddToFolder, setShowAddToFolder] = useState(false);

  // Auto-open drawer when image_id is in URL params
  const hasOpenedLinked = useRef(false);
  const { data: linkedImage } = useQuery({
    queryKey: ['images', Number(imageIdParam)],
    queryFn: () => imagesApi.get(Number(imageIdParam)),
    enabled: !!imageIdParam,
  });

  useEffect(() => {
    if (linkedImage && !hasOpenedLinked.current) {
      hasOpenedLinked.current = true;
      setSelectedImage(linkedImage);
    }
  }, [linkedImage]);

  const { data, isLoading } = useQuery({
    queryKey: [queryKeyPrefix, statusFilter, filterMode, page],
    queryFn: () =>
      fetchImages({
        status: filterMode === 'exact' ? statusFilter : undefined,
        min_status: filterMode === 'min_status' ? statusFilter : undefined,
        skip: page * limit,
        limit,
      }),
  });

  const { data: jobs } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
  });

  const hasBatchRunning = jobs?.items.some(
    (j) => j.job_type === 'batch_reprocess' && (j.status === 'running' || j.status === 'pending')
  ) ?? false;

  const reprocessSelectedMutation = useMutation({
    mutationFn: (imageIds: number[]) => jobsApi.reprocessSelected(imageIds),
    onSuccess: (data) => {
      toast.success(`Reprocessing ${selectedIds.size} images`, {
        description: `Job #${data.job_id}`,
        action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
      });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
      queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] });
      setSelectedIds(new Set());
      setSelectMode(false);
    },
    onError: () => {
      toast.error('Failed to start reprocessing');
    },
  });

  const reprocessFolderMutation = useMutation({
    mutationFn: (fId: number) => foldersApi.reprocess(fId),
    onSuccess: (data) => {
      toast.success(`Reprocessing folder`, {
        description: `Job #${data.job_id} — ${data.total} images`,
        action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
      });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
    },
    onError: () => {
      toast.error('Failed to reprocess folder');
    },
  });

  const removeFromFolderMutation = useMutation({
    mutationFn: (imageIds: number[]) => foldersApi.removeImages(folderId!, imageIds),
    onSuccess: (data) => {
      toast.success(`Removed ${data.removed} images from folder`);
      queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      setSelectedIds(new Set());
      setSelectMode(false);
    },
    onError: () => {
      toast.error('Failed to remove images');
    },
  });

  const handleToggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    if (!data?.items) return;
    const allOnPage = data.items.map((img) => img.id);
    const allSelected = allOnPage.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        allOnPage.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        allOnPage.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{title}</h1>

        <div className="flex items-center gap-2">
          {/* Folder reprocess button */}
          {folderId && (
            <>
              <button
                onClick={() => reprocessFolderMutation.mutate(folderId)}
                disabled={reprocessFolderMutation.isPending || hasBatchRunning}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                <RefreshCw className={cn('h-3.5 w-3.5', reprocessFolderMutation.isPending && 'animate-spin')} />
                Reprocess All
              </button>
              <div className="w-px h-6 bg-border" />
            </>
          )}

          {/* Select mode toggle */}
          {selectMode ? (
            <>
              <button
                onClick={handleSelectAll}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted'
                )}
              >
                {data?.items && data.items.every((img) => selectedIds.has(img.id))
                  ? 'Deselect Page'
                  : 'Select Page'}
              </button>
              <button
                onClick={exitSelectMode}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted'
                )}
              >
                <X className="h-3.5 w-3.5" />
                Cancel
              </button>
              <div className="w-px h-6 bg-border" />
            </>
          ) : (
            <>
              <button
                onClick={() => setSelectMode(true)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted'
                )}
              >
                <CheckSquare className="h-3.5 w-3.5" />
                Select
              </button>
              <div className="w-px h-6 bg-border" />
            </>
          )}

          {/* Status Filter */}
          {statusFilters.map((filter) => (
            <button
              key={filter.label}
              onClick={() => {
                setStatusFilter(filter.value);
                setFilterMode(filter.mode);
                setPage(0);
              }}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm transition-colors',
                statusFilter === filter.value
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border hover:bg-muted'
              )}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : data?.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <p className="text-muted-foreground">No images found</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {data?.items.map((image) => (
              <ImageCard
                key={image.id}
                image={image}
                onClick={selectMode ? undefined : () => setSelectedImage(image)}
                showStatus
                selectable={selectMode}
                selected={selectedIds.has(image.id)}
                onSelect={handleToggleSelect}
              />
            ))}
          </div>

          {/* Pagination */}
          {data && data.total > limit && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-4 py-2 border border-border rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <span className="text-sm text-muted-foreground">
                Page {page + 1} of {Math.ceil(data.total / limit)}
              </span>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={(page + 1) * limit >= data.total}
                className="px-4 py-2 border border-border rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      {/* Floating action bar for selection */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-white border border-border rounded-xl shadow-lg px-4 py-3 flex items-center gap-3 z-50">
          <span className="text-sm font-medium">
            {selectedIds.size} image{selectedIds.size !== 1 ? 's' : ''} selected
          </span>
          <button
            onClick={() => reprocessSelectedMutation.mutate(Array.from(selectedIds))}
            disabled={reprocessSelectedMutation.isPending || hasBatchRunning}
            title={hasBatchRunning ? 'A batch reprocess job is already running' : undefined}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', reprocessSelectedMutation.isPending && 'animate-spin')} />
            Reprocess
          </button>

          {/* Add to folder (when NOT in a folder view) */}
          {!folderId && (
            <button
              onClick={() => setShowAddToFolder(true)}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                'border border-border hover:bg-muted'
              )}
            >
              <FolderPlus className="h-3.5 w-3.5" />
              Add to Folder
            </button>
          )}

          {/* Remove from folder (when IN a folder view) */}
          {folderId && (
            <button
              onClick={() => removeFromFolderMutation.mutate(Array.from(selectedIds))}
              disabled={removeFromFolderMutation.isPending}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                'border border-red-300 text-red-700 hover:bg-red-50',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove from Folder
            </button>
          )}

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
          imageIds={Array.from(selectedIds)}
          onClose={() => setShowAddToFolder(false)}
          onDone={() => {
            setShowAddToFolder(false);
            setSelectedIds(new Set());
            setSelectMode(false);
          }}
        />
      )}

      {selectedImage && (
        <ImageDrawer
          image={selectedImage}
          onClose={() => setSelectedImage(null)}
        />
      )}
    </div>
  );
}

