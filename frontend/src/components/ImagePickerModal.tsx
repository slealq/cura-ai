'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { imagesApi, generationApi } from '@/lib/api';
import { X, Loader2, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ImagePickerModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (sourceType: 'gallery' | 'generated', ids: number[]) => void;
  selectedGalleryIds: number[];
  selectedGeneratedIds: number[];
  maxSelection?: number;
}

export default function ImagePickerModal({
  open,
  onClose,
  onSelect,
  selectedGalleryIds,
  selectedGeneratedIds,
  maxSelection = 3,
}: ImagePickerModalProps) {
  const [tab, setTab] = useState<'gallery' | 'generated'>('gallery');
  const [localGalleryIds, setLocalGalleryIds] = useState<number[]>(selectedGalleryIds);
  const [localGeneratedIds, setLocalGeneratedIds] = useState<number[]>(selectedGeneratedIds);
  const [page, setPage] = useState(0);
  const limit = 40;

  const totalSelected = localGalleryIds.length + localGeneratedIds.length +
    (tab === 'gallery' ? selectedGeneratedIds.length : selectedGalleryIds.length) -
    (tab === 'gallery' ? localGeneratedIds.length : localGalleryIds.length);

  // Compute actual total selected across both tabs
  const actualTotalSelected = localGalleryIds.length + localGeneratedIds.length;
  const remaining = maxSelection - actualTotalSelected;

  const { data: galleryData, isLoading: galleryLoading } = useQuery({
    queryKey: ['picker-gallery', page],
    queryFn: () => imagesApi.list({ skip: page * limit, limit, status: 'ingested,tagged,described,embedded' }),
    enabled: open && tab === 'gallery',
  });

  const { data: generatedData, isLoading: generatedLoading } = useQuery({
    queryKey: ['picker-generated', page],
    queryFn: () => generationApi.listImages({ skip: page * limit, limit, status: 'completed' }),
    enabled: open && tab === 'generated',
  });

  if (!open) return null;

  const toggleGallery = (id: number) => {
    if (localGalleryIds.includes(id)) {
      setLocalGalleryIds(localGalleryIds.filter((i) => i !== id));
    } else if (remaining > 0 || localGalleryIds.includes(id)) {
      setLocalGalleryIds([...localGalleryIds, id]);
    }
  };

  const toggleGenerated = (id: number) => {
    if (localGeneratedIds.includes(id)) {
      setLocalGeneratedIds(localGeneratedIds.filter((i) => i !== id));
    } else if (remaining > 0 || localGeneratedIds.includes(id)) {
      setLocalGeneratedIds([...localGeneratedIds, id]);
    }
  };

  const handleDone = () => {
    if (tab === 'gallery') {
      onSelect('gallery', localGalleryIds);
    } else {
      onSelect('generated', localGeneratedIds);
    }
    onClose();
  };

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
            <div className="flex items-center gap-4">
              <h3 className="font-semibold">Select Source Images</h3>
              <span className="text-sm text-muted-foreground">
                {actualTotalSelected}/{maxSelection} selected
              </span>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-muted rounded-lg transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Tabs */}
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
              Gallery
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

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {tab === 'gallery' ? (
              galleryLoading ? (
                <div className="flex items-center justify-center h-32">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !galleryData?.items.length ? (
                <p className="text-center text-muted-foreground py-8">No images available</p>
              ) : (
                <>
                  <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 gap-2">
                    {galleryData.items.map((img) => {
                      const isSelected = localGalleryIds.includes(img.id);
                      const thumbnailSrc = img.thumbnail_uri_small
                        ? imagesApi.getThumbnailUrl(img.thumbnail_uri_small.split('/').pop() || '')
                        : null;
                      return (
                        <button
                          key={img.id}
                          onClick={() => toggleGallery(img.id)}
                          disabled={!isSelected && remaining <= 0}
                          className={cn(
                            'relative aspect-square rounded-lg overflow-hidden border-2 transition-all',
                            isSelected
                              ? 'border-primary ring-2 ring-primary/30'
                              : 'border-transparent hover:border-border',
                            !isSelected && remaining <= 0 && 'opacity-40 cursor-not-allowed'
                          )}
                        >
                          {thumbnailSrc ? (
                            <img src={thumbnailSrc} alt="" className="w-full h-full object-cover" loading="lazy" />
                          ) : (
                            <div className="w-full h-full bg-muted/30" />
                          )}
                          {isSelected && (
                            <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                              <Check className="h-6 w-6 text-primary" />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {galleryData.total > limit && (
                    <div className="flex justify-center gap-2 mt-4">
                      <button
                        onClick={() => setPage(Math.max(0, page - 1))}
                        disabled={page === 0}
                        className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
                      >
                        Previous
                      </button>
                      <span className="px-3 py-1 text-sm text-muted-foreground">
                        Page {page + 1} of {Math.ceil(galleryData.total / limit)}
                      </span>
                      <button
                        onClick={() => setPage(page + 1)}
                        disabled={(page + 1) * limit >= galleryData.total}
                        className="px-3 py-1 text-sm border border-border rounded-lg disabled:opacity-50"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </>
              )
            ) : (
              generatedLoading ? (
                <div className="flex items-center justify-center h-32">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !generatedData?.items.length ? (
                <p className="text-center text-muted-foreground py-8">No generated images available</p>
              ) : (
                <>
                  <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 gap-2">
                    {generatedData.items.map((img) => {
                      const isSelected = localGeneratedIds.includes(img.id);
                      const thumbnailSrc = img.thumbnail_uri_medium
                        ? generationApi.getThumbnailUrl(img.thumbnail_uri_medium.split('/').pop() || '')
                        : null;
                      return (
                        <button
                          key={img.id}
                          onClick={() => toggleGenerated(img.id)}
                          disabled={!isSelected && remaining <= 0}
                          className={cn(
                            'relative aspect-square rounded-lg overflow-hidden border-2 transition-all',
                            isSelected
                              ? 'border-primary ring-2 ring-primary/30'
                              : 'border-transparent hover:border-border',
                            !isSelected && remaining <= 0 && 'opacity-40 cursor-not-allowed'
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
                          {isSelected && (
                            <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                              <Check className="h-6 w-6 text-primary" />
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
              className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
