'use client';

import { Suspense, useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { imagesApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import { cn } from '@/lib/utils';
import type { Image } from '@/types';

type FilterMode = 'none' | 'min_status' | 'exact';

const statusFilters: { value: string | undefined; label: string; mode: FilterMode }[] = [
  { value: undefined, label: 'All', mode: 'none' },
  { value: 'ingested', label: 'Ingested', mode: 'min_status' },
  { value: 'tagged', label: 'Tagged', mode: 'min_status' },
  { value: 'described', label: 'Described', mode: 'min_status' },
  { value: 'embedded', label: 'Embedded', mode: 'min_status' },
  { value: 'clustered', label: 'Clustered', mode: 'min_status' },
  { value: 'failed', label: 'Failed', mode: 'exact' },
];

export default function ImagesPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <ImagesContent />
    </Suspense>
  );
}

function ImagesContent() {
  const searchParams = useSearchParams();
  const imageIdParam = searchParams.get('image_id');
  const [selectedImage, setSelectedImage] = useState<Image | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [filterMode, setFilterMode] = useState<FilterMode>('none');
  const [page, setPage] = useState(0);
  const limit = 50;

  // Auto-open drawer when image_id is in URL params (only once)
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
    queryKey: ['images', statusFilter, filterMode, page],
    queryFn: () =>
      imagesApi.list({
        status: filterMode === 'exact' ? statusFilter : undefined,
        min_status: filterMode === 'min_status' ? statusFilter : undefined,
        skip: page * limit,
        limit,
      }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">All Images</h1>

        {/* Status Filter */}
        <div className="flex items-center gap-2">
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
                onClick={() => setSelectedImage(image)}
                showStatus
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

      {selectedImage && (
        <ImageDrawer
          image={selectedImage}
          onClose={() => setSelectedImage(null)}
        />
      )}
    </div>
  );
}
