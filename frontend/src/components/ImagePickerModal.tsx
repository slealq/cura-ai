'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { imagesApi, foldersApi, clustersApi, generationApi, authUrl } from '@/lib/api';
import { X, Loader2, Check, ChevronLeft, FolderOpen, LayoutGrid } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface PickedImage {
  type: 'gallery' | 'generated';
  id: number;
  previewUrl: string;
}

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

  if (!open) return null;

  const isInsideCollection = browseFolderId !== null || browseClusterId !== null;

  const isSelectedId = (id: number) => selected.some((s) => s.id === id) || alreadySelectedIds.includes(id);

  const toggleImage = (id: number, type: 'gallery' | 'generated', thumbUrl: string) => {
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

  // Render image grid for level 2 (gallery images in folder/cluster)
  const renderImageGrid = (
    images: Array<{ id: number; thumbnail_uri_small?: string | null; thumbnail_uri_medium?: string | null }>,
    total: number,
  ) => (
    <>
      <div className="grid grid-cols-5 sm:grid-cols-6 md:grid-cols-8 gap-1.5">
        {images.map((img) => {
          const checked = isSelectedId(img.id);
          const thumbUri = img.thumbnail_uri_small || img.thumbnail_uri_medium;
          const thumbnailSrc = galleryThumbUrl(thumbUri);
          return (
            <button
              key={img.id}
              onClick={() => toggleImage(img.id, 'gallery', thumbnailSrc)}
              disabled={!checked && remaining <= 0}
              className={cn(
                'relative aspect-square rounded-md overflow-hidden border-2 transition-all',
                checked
                  ? 'border-primary ring-2 ring-primary/30'
                  : 'border-transparent hover:border-border',
                !checked && remaining <= 0 && 'opacity-40 cursor-not-allowed'
              )}
            >
              {thumbnailSrc ? (
                <img src={thumbnailSrc} alt="" className="w-full h-full object-cover" loading="lazy" />
              ) : (
                <div className="w-full h-full bg-muted/30" />
              )}
              {checked && (
                <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                  <Check className="h-5 w-5 text-primary" />
                </div>
              )}
            </button>
          );
        })}
      </div>
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
          className="bg-card rounded-xl shadow-xl max-w-4xl w-full max-h-[85vh] flex flex-col"
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
                                  <img
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
                                  <img
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
                  <div className="grid grid-cols-5 sm:grid-cols-6 md:grid-cols-8 gap-1.5">
                    {generatedData.items.map((img) => {
                      const checked = isSelectedId(img.id);
                      const thumbnailSrc = generatedThumbUrl(img.thumbnail_uri_medium);
                      return (
                        <button
                          key={img.id}
                          onClick={() => toggleImage(img.id, 'generated', thumbnailSrc)}
                          disabled={!checked && remaining <= 0}
                          className={cn(
                            'relative aspect-square rounded-md overflow-hidden border-2 transition-all',
                            checked
                              ? 'border-primary ring-2 ring-primary/30'
                              : 'border-transparent hover:border-border',
                            !checked && remaining <= 0 && 'opacity-40 cursor-not-allowed'
                          )}
                        >
                          {thumbnailSrc ? (
                            <img src={thumbnailSrc} alt="" className="w-full h-full object-cover" loading="lazy" />
                          ) : img.status === 'completed' ? (
                            <div className="w-full h-full bg-muted/30" />
                          ) : (
                            <div className="w-full h-full bg-muted/30 flex items-center justify-center">
                              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                            </div>
                          )}
                          {checked && (
                            <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                              <Check className="h-5 w-5 text-primary" />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
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
          <div className="flex justify-end gap-3 p-4 border-t border-border">
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
    </>
  );
}
