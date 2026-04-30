'use client';

import { Suspense, useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useRouter } from 'next/navigation';
import { Loader2, CheckSquare, X, RefreshCw, FolderPlus, Trash2, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { imagesApi, jobsApi, foldersApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import AddToFolderDialog from '@/components/AddToFolderDialog';
import DescribeAllDialog from '@/components/DescribeAllDialog';
import { cn } from '@/lib/utils';
import type { Image, ImageListResponse } from '@/types';

type FilterKey = 'failed' | 'not_described' | 'not_clustered';

const imageFilters: { key: FilterKey; label: string }[] = [
  { key: 'failed', label: 'Failed' },
  { key: 'not_described', label: 'Not described' },
  { key: 'not_clustered', label: 'Not clustered' },
];

interface ImageGridProps {
  title: string;
  queryKeyPrefix: string;
  fetchImages: (params: {
    status?: string;
    min_status?: string;
    max_status?: string;
    in_folder?: boolean;
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
  const [activeFilter, setActiveFilter] = useState<FilterKey | null>(null);
  const [page, setPage] = useState(0);
  const limit = 50;

  // Multi-select state
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // Add to folder dialog
  const [showAddToFolder, setShowAddToFolder] = useState(false);

  // Describe all dialog
  const [showDescribeAll, setShowDescribeAll] = useState(false);

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

  const filterParams = (() => {
    switch (activeFilter) {
      case 'failed': return { status: 'failed' };
      case 'not_described': return { max_status: 'tagged' };
      case 'not_clustered': return { max_status: 'embedded' };
      default: return {};
    }
  })();

  const { data, isLoading } = useQuery({
    queryKey: [queryKeyPrefix, activeFilter, page],
    queryFn: () =>
      fetchImages({
        ...filterParams,
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
    (j) => (j.job_type === 'batch_reprocess' || j.job_type === 'batch_describe') && (j.status === 'running' || j.status === 'pending')
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

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const deleteSelectedMutation = useMutation({
    mutationFn: (imageIds: number[]) => imagesApi.batchDelete(imageIds),
    onSuccess: (data) => {
      toast.success(`Deleted ${data.deleted} images`);
      queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      setSelectedIds(new Set());
      setSelectMode(false);
    },
    onError: () => {
      toast.error('Failed to delete images');
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
          {/* Folder describe button */}
          {folderId && (
            <>
              <button
                onClick={() => setShowDescribeAll(true)}
                disabled={hasBatchRunning}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors',
                  'border border-border hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                <FileText className="h-3.5 w-3.5" />
                Describe All
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

          {/* Filters */}
          {imageFilters.map((filter) => (
            <button
              key={filter.key}
              onClick={() => {
                setActiveFilter((prev) => prev === filter.key ? null : filter.key);
                setPage(0);
              }}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm transition-colors',
                activeFilter === filter.key
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
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-card border border-border rounded-xl shadow-lg px-4 py-3 flex items-center gap-3 z-50">
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

          {/* Add to folder */}
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

          {/* Remove from folder (when IN a folder view) */}
          {folderId && (
            <button
              onClick={() => removeFromFolderMutation.mutate(Array.from(selectedIds))}
              disabled={removeFromFolderMutation.isPending}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                'border border-border hover:bg-muted',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove from Folder
            </button>
          )}

          {/* Delete images */}
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
              'border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/30'
            )}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
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
          imageIds={Array.from(selectedIds)}
          onClose={() => setShowAddToFolder(false)}
          onDone={() => {
            setShowAddToFolder(false);
            setSelectedIds(new Set());
            setSelectMode(false);
            queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
          }}
        />
      )}

      {/* Describe All dialog */}
      {showDescribeAll && folderId && (
        <DescribeAllDialog
          folderId={folderId}
          imageCount={data?.total ?? 0}
          onClose={() => setShowDescribeAll(false)}
          onStarted={(jobId, total) => {
            setShowDescribeAll(false);
            toast.success(`Describing ${total} images`, {
              description: `Job #${jobId}`,
              action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
            });
            queryClient.invalidateQueries({ queryKey: ['jobs'] });
            queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
          }}
        />
      )}

      {/* Delete confirmation */}
      {showDeleteConfirm && (
        <>
          <div className="fixed inset-0 bg-black/50 z-50" onClick={() => setShowDeleteConfirm(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-card rounded-xl shadow-xl max-w-sm w-full p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-lg font-semibold">Delete Images</h3>
              <p className="text-sm text-muted-foreground">
                Permanently delete {selectedIds.size} image{selectedIds.size !== 1 ? 's' : ''}? This cannot be undone.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    deleteSelectedMutation.mutate(Array.from(selectedIds));
                  }}
                  className="px-4 py-2 text-sm text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        </>
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

