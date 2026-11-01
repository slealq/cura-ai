'use client';

import LibraryImage from '@/components/LibraryImage';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { imagesApi, foldersApi, clustersApi, generationApi, authUrl } from '@/lib/api';
import { X, Loader2, Check, ChevronLeft, ChevronRight, FolderOpen, LayoutGrid, Maximize2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface PickedImage {
  type: 'gallery' | 'generated';
  id: number;
  previewUrl: string;
}

interface PickerItem {
  id: number;
  type: PickedImage['type'];
  thumbnail: string;
  full: string;
}

const GRID = 'grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2';

interface ImagePickerModalProps {
  open: boolean;
  onClose: () => void;
  onDone: (items: PickedImage[]) => void;
  alreadySelectedIds?: number[];
  maxSelection?: number;
}

export default function ImagePickerModal({
  open,
  onClose,
  onDone,
  alreadySelectedIds = [],
  maxSelection = 3,
}: ImagePickerModalProps) {
  const [tab, setTab] = useState<'gallery' | 'generated'>('gallery');

  // Track selected items with their preview URLs
  const [selected, setSelected] = useState<PickedImage[]>([]);

  // Large preview of one image, stepping through the grid it was opened from
  const [preview, setPreview] = useState<{ items: PickerItem[]; index: number } | null>(null);

  // Two-level browse: null = show folders/clusters, number = show images inside
  const [browseFolderId, setBrowseFolderId] = useState<number | null>(null);
  const [browseClusterId, setBrowseClusterId] = useState<number | null>(null);
  const [browseLabel, setBrowseLabel] = useState('');

  const [page, setPage] = useState(0);
  const limit = 40;

  const totalSelected = selected.length;
  const remaining = maxSelection - alreadySelectedIds.length - totalSelected;

  // Level 1: Folders and clusters
  const { data: foldersData, isLoading: foldersLoading } = useQuery({
    queryKey: ['picker-folders'],
    queryFn: () => foldersApi.list({ limit: 100 }),
    enabled: open && tab === 'gallery' && browseFolderId === null && browseClusterId === null,
  });

  const { data: clustersData, isLoading: clustersLoading } = useQuery({
    queryKey: ['picker-clusters'],
    queryFn: () => clustersApi.list({ limit: 100 }),
    enabled: open && tab === 'gallery' && browseFolderId === null && browseClusterId === null,
  });

  // Level 2: Images inside a folder or cluster
  const { data: folderImages, isLoading: folderImagesLoading } = useQuery({
    queryKey: ['picker-folder-images', browseFolderId, page],
    queryFn: () => foldersApi.listImages(browseFolderId!, { skip: page * limit, limit, min_status: 'ingested' }),
    enabled: open && tab === 'gallery' && browseFolderId !== null,
  });

  const { data: clusterDetail, isLoading: clusterImagesLoading } = useQuery({
    queryKey: ['picker-cluster-images', browseClusterId],
    queryFn: () => clustersApi.get(browseClusterId!),
    enabled: open && tab === 'gallery' && browseClusterId !== null,
  });

  // Generated tab
  const { data: generatedData, isLoading: generatedLoading } = useQuery({
    queryKey: ['picker-generated', page],
    queryFn: () => generationApi.listImages({ skip: page * limit, limit, status: 'completed' }),
    enabled: open && tab === 'generated',
  });

  useEffect(() => {
    if (!preview) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopImmediatePropagation();
        setPreview(null);
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        const step = event.key === 'ArrowLeft' ? -1 : 1;
        setPreview(current => current && { ...current, index: Math.min(current.items.length - 1, Math.max(0, current.index + step)) });
      }
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [preview]);

  if (!open) return null;

  const current = preview?.items[preview.index];
  const isInsideCollection = browseFolderId !== null || browseClusterId !== null;

  const isSelectedId = (id: number) => selected.some((s) => s.id === id) || alreadySelectedIds.includes(id);

  const toggleImage = (id: number, type: 'gallery' | 'generated', thumbUrl: string) => {
    if (alreadySelectedIds.includes(id)) return;
    const existing = selected.find((s) => s.id === id && s.type === type);
    if (existing) {
      setSelected(selected.filter((s) => s !== existing));
    } else if (remaining > 0) {
      setSelected([...selected, { type, id, previewUrl: thumbUrl }]);
    }
  };

  const handleDone = () => {
    onDone(selected);
    onClose();
  };

  const goBack = () => {
    setBrowseFolderId(null);
    setBrowseClusterId(null);
    setBrowseLabel('');
    setPage(0);
  };

  const openFolder = (id: number, name: string) => {
    setBrowseFolderId(id);
    setBrowseLabel(name);
    setPage(0);
  };

  const openCluster = (id: number, name: string) => {
    setBrowseClusterId(id);
    setBrowseLabel(name);
    setPage(0);
  };

  // Get cover thumbnail URL for folders/clusters
  const getCoverUrl = (url: string | null) => {
    if (!url) return null;
    return url.startsWith('http') ? url : authUrl(url);
  };

  // Build a thumbnail URL from a URI path
  const galleryThumbUrl = (uri: string | null | undefined) => {
    if (!uri) return '';
    return imagesApi.getThumbnailUrl(uri.split('/').pop() || '');
  };

  const generatedThumbUrl = (uri: string | null | undefined) => {
    if (!uri) return '';
    return generationApi.getThumbnailUrl(uri.split('/').pop() || '');
  };

  const renderTiles = (items: PickerItem[]) => (
    <div className={GRID}>
      {items.map((item, index) => {
        const checked = isSelectedId(item.id);
        return (
          <div key={item.id} className="group relative aspect-square">
            <button
              onClick={() => toggleImage(item.id, item.type, item.thumbnail)}
              disabled={!checked && remaining <= 0}
              aria-label={`${checked ? 'Unselect' : 'Select'} image ${item.id}`}
              aria-pressed={checked}
              className={cn(
                'relative h-full w-full rounded-md overflow-hidden border-2 transition-all',
                checked
                  ? 'border-primary ring-2 ring-primary/30'
                  : 'border-transparent hover:border-border',
                !checked && remaining <= 0 && 'opacity-40 cursor-not-allowed'
              )}
            >
              {item.thumbnail ? (
                <LibraryImage src={item.thumbnail} alt="" className="w-full h-full object-cover" loading="lazy" />
              ) : (
                <div className="w-full h-full bg-muted/30" />
              )}
              {checked && (
                <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                  <Check className="h-5 w-5 text-primary" />
                </div>
              )}
            </button>
            <button
              onClick={() => setPreview({ items, index })}
              aria-label={`View image ${item.id} large`}
              title="View large"
              className="absolute right-1.5 top-1.5 grid h-8 w-8 place-items-center rounded-md bg-black/65 text-white opacity-0 transition-opacity hover:bg-black/80 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );

  // Render image grid for level 2 (gallery images in folder/cluster)
  const renderImageGrid = (
    images: Array<{ id: number; object_key: string; thumbnail_uri_small?: string | null; thumbnail_uri_medium?: string | null }>,
    total: number,
  ) => (
    <>
      {renderTiles(images.map(img => ({
        id: img.id,
        type: 'gallery' as const,
        thumbnail: galleryThumbUrl(img.thumbnail_uri_medium || img.thumbnail_uri_small),
        full: imagesApi.getImageUrl(img.object_key.split('/').pop() || ''),
      })))}
      {total > limit && (
        <div className="flex justify-center gap-2 mt-4">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-muted-foreground">
            Page {page + 1} of {Math.ceil(total / limit)}
          </span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={(page + 1) * limit >= total}
            className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </>
  );

  return (
    <>
      <div className="fixed inset-0 bg-black/70 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="mobile-modal bg-card rounded-xl shadow-xl max-w-6xl w-full max-h-[90vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-border">
            <div className="flex items-center gap-3">
              {isInsideCollection && (
                <button onClick={goBack} className="p-1 hover:bg-muted rounded-lg transition-colors">
                  <ChevronLeft className="h-5 w-5" />
                </button>
              )}
              <h3 className="font-semibold">
                {isInsideCollection ? browseLabel : 'Select Source Images'}
              </h3>
              <span className="text-sm text-muted-foreground">
                {totalSelected + alreadySelectedIds.length}/{maxSelection} selected
              </span>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-muted rounded-lg transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Tabs — only show at top level */}
          {!isInsideCollection && (
            <div className="flex border-b border-border">
              <button
                onClick={() => { setTab('gallery'); setPage(0); }}
                className={cn(
                  'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                  tab === 'gallery'
                    ? 'border-primary text-primary'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                )}
              >
                Library
              </button>
              <button
                onClick={() => { setTab('generated'); setPage(0); }}
                className={cn(
                  'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                  tab === 'generated'
                    ? 'border-primary text-primary'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                )}
              >
                Generated
              </button>
            </div>
          )}

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {tab === 'gallery' ? (
              // Gallery tab
              isInsideCollection ? (
                // Level 2: Images inside folder or cluster
                browseFolderId !== null ? (
                  folderImagesLoading ? (
                    <div className="flex items-center justify-center h-32">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                  ) : !folderImages?.items.length ? (
                    <p className="text-center text-muted-foreground py-8">No images in this folder</p>
                  ) : (
                    renderImageGrid(folderImages.items, folderImages.total)
                  )
                ) : (
                  // Cluster images
                  clusterImagesLoading ? (
                    <div className="flex items-center justify-center h-32">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                  ) : !clusterDetail?.images.length ? (
                    <p className="text-center text-muted-foreground py-8">No images in this cluster</p>
                  ) : (
                    renderImageGrid(clusterDetail.images, clusterDetail.images.length)
                  )
                )
              ) : (
                // Level 1: Folders and clusters grid
                (foldersLoading || clustersLoading) ? (
                  <div className="flex items-center justify-center h-32">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  <div className="space-y-5">
                    {/* Folders */}
                    {foldersData?.items && foldersData.items.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Folders</h4>
                        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                          {foldersData.items.map((folder) => (
                            <button
                              key={folder.id}
                              onClick={() => openFolder(folder.id, folder.name)}
                              className="group text-left rounded-lg border border-border hover:border-primary/50 overflow-hidden transition-colors"
                            >
                              <div className="aspect-square bg-muted/30 relative">
                                {folder.cover_thumbnail_url ? (
                                  <LibraryImage
                                    src={getCoverUrl(folder.cover_thumbnail_url)!}
                                    alt=""
                                    className="w-full h-full object-cover"
                                    loading="lazy"
                                  />
                                ) : (
                                  <div className="w-full h-full flex items-center justify-center">
                                    <FolderOpen className="h-8 w-8 text-muted-foreground/40" />
                                  </div>
                                )}
                              </div>
                              <div className="p-1.5">
                                <p className="text-xs font-medium truncate">{folder.name}</p>
                                <p className="text-[10px] text-muted-foreground">{folder.image_count} images</p>
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Clusters */}
                    {clustersData?.items && clustersData.items.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Clusters</h4>
                        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                          {clustersData.items.map((cluster) => (
                            <button
                              key={cluster.id}
                              onClick={() => openCluster(cluster.id, cluster.display_name || cluster.summary_title || `Cluster #${cluster.id}`)}
                              className="group text-left rounded-lg border border-border hover:border-primary/50 overflow-hidden transition-colors"
                            >
                              <div className="aspect-square bg-muted/30 relative">
                                {cluster.cover_thumbnail_url ? (
                                  <LibraryImage
                                    src={getCoverUrl(cluster.cover_thumbnail_url)!}
                                    alt=""
                                    className="w-full h-full object-cover"
                                    loading="lazy"
                                  />
                                ) : (
                                  <div className="w-full h-full flex items-center justify-center">
                                    <LayoutGrid className="h-8 w-8 text-muted-foreground/40" />
                                  </div>
                                )}
                              </div>
                              <div className="p-1.5">
                                <p className="text-xs font-medium truncate">
                                  {cluster.display_name || cluster.summary_title || `Cluster #${cluster.id}`}
                                </p>
                                <p className="text-[10px] text-muted-foreground">{cluster.size} images</p>
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {(!foldersData?.items.length && !clustersData?.items.length) && (
                      <p className="text-center text-muted-foreground py-8">No folders or clusters available</p>
                    )}
                  </div>
                )
              )
            ) : (
              // Generated tab — flat grid (usually smaller set)
              generatedLoading ? (
                <div className="flex items-center justify-center h-32">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !generatedData?.items.length ? (
                <p className="text-center text-muted-foreground py-8">No generated images available</p>
              ) : (
                <>
                  {renderTiles(generatedData.items.map(img => ({
                    id: img.id,
                    type: 'generated' as const,
                    thumbnail: generatedThumbUrl(img.thumbnail_uri_medium),
                    full: generationApi.getImageUrl(img.id),
                  })))}
                  {generatedData.total > limit && (
                    <div className="flex justify-center gap-2 mt-4">
                      <button
                        onClick={() => setPage(Math.max(0, page - 1))}
                        disabled={page === 0}
                        className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
                      >
                        Previous
                      </button>
                      <span className="px-3 py-1 text-sm text-muted-foreground">
                        Page {page + 1} of {Math.ceil(generatedData.total / limit)}
                      </span>
                      <button
                        onClick={() => setPage(page + 1)}
                        disabled={(page + 1) * limit >= generatedData.total}
                        className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </>
              )
            )}
          </div>

          {/* Footer */}
          <div className="mobile-modal-actions flex justify-end gap-3 p-4 border-t border-border">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDone}
              disabled={totalSelected === 0}
              className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium disabled:opacity-50"
            >
              Done ({totalSelected})
            </button>
          </div>
        </div>
      </div>

      {current && (
        <div role="dialog" aria-modal="true" aria-label="Image preview" className="fixed inset-0 z-[60] flex flex-col bg-black text-white">
          <div className="flex items-center justify-between p-3">
            <span className="text-sm text-white/70">{preview!.index + 1} of {preview!.items.length}</span>
            <button aria-label="Close preview" onClick={() => setPreview(null)} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="relative min-h-0 flex-1">
            {/* The thumbnail shows at once; the full image loads over it. */}
            {current.thumbnail && <LibraryImage src={current.thumbnail} alt="" className="absolute inset-0 h-full w-full object-contain" />}
            <LibraryImage key={current.full} src={current.full} alt={`Image ${current.id}`} className="absolute inset-0 h-full w-full object-contain" />
            <button aria-label="Previous image" disabled={preview!.index === 0} onClick={() => setPreview({ ...preview!, index: preview!.index - 1 })} className="absolute left-2 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-black/50 hover:bg-black/70 disabled:opacity-30">
              <ChevronLeft className="h-6 w-6" />
            </button>
            <button aria-label="Next image" disabled={preview!.index === preview!.items.length - 1} onClick={() => setPreview({ ...preview!, index: preview!.index + 1 })} className="absolute right-2 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-black/50 hover:bg-black/70 disabled:opacity-30">
              <ChevronRight className="h-6 w-6" />
            </button>
          </div>
          <div className="flex items-center justify-end gap-3 p-3 pb-[max(12px,env(safe-area-inset-bottom))]">
            {alreadySelectedIds.includes(current.id) ? (
              <span className="text-sm text-white/70">Already added</span>
            ) : (
              <button
                onClick={() => toggleImage(current.id, current.type, current.thumbnail)}
                disabled={!isSelectedId(current.id) && remaining <= 0}
                className="min-h-10 rounded-lg border border-white/30 px-4 text-sm hover:bg-white/10 disabled:opacity-40"
              >
                {isSelectedId(current.id) ? 'Unselect' : 'Select'}
              </button>
            )}
            <button
              onClick={() => { setPreview(null); handleDone(); }}
              disabled={totalSelected === 0}
              className="min-h-10 rounded-lg bg-white px-4 text-sm font-medium text-black disabled:opacity-40"
            >
              Done ({totalSelected})
            </button>
          </div>
        </div>
      )}
    </>
  );
}
