'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X, ExternalLink, RefreshCw } from 'lucide-react';
import type { Image } from '@/types';
import { imagesApi } from '@/lib/api';
import { cn, formatDate, formatFileSize, getStatusColor } from '@/lib/utils';
import ImageCard from './ImageCard';

interface ImageDrawerProps {
  image: Image;
  onClose: () => void;
}

export default function ImageDrawer({ image, onClose }: ImageDrawerProps) {
  const { data: similarImages } = useQuery({
    queryKey: ['similar-images', image.id],
    queryFn: () => imagesApi.getSimilar(image.id, 6),
    enabled: image.status === 'embedded' || image.status === 'clustered',
  });

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  const imageUrl = imagesApi.getImageUrl(image.object_key);
  const tags = image.metadata?.tags || {};

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full max-w-xl bg-white shadow-xl z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-border px-6 py-4 flex items-center justify-between">
          <h2 className="font-semibold truncate">
            {image.original_filename || image.object_key}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Image */}
          <div className="rounded-lg overflow-hidden bg-muted">
            <img
              src={imageUrl}
              alt={image.metadata?.caption_short || ''}
              className="w-full h-auto"
            />
          </div>

          {/* Status & Actions */}
          <div className="flex items-center justify-between">
            <span
              className={cn(
                'px-3 py-1 rounded-full text-sm font-medium',
                getStatusColor(image.status)
              )}
            >
              {image.status}
            </span>
            <div className="flex items-center gap-2">
              <a
                href={imageUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-2 hover:bg-muted rounded-lg transition-colors"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
              <button
                onClick={() => imagesApi.reprocess(image.id)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
              >
                <RefreshCw className="h-4 w-4" />
                Reprocess
              </button>
            </div>
          </div>

          {/* Caption */}
          {image.metadata?.caption_short && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Caption
              </h3>
              <p className="text-sm">{image.metadata.caption_short}</p>
            </div>
          )}

          {/* Description */}
          {image.metadata?.description_long && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Design Notes
              </h3>
              <div className="text-sm whitespace-pre-line">
                {image.metadata.description_long}
              </div>
            </div>
          )}

          {/* Tags */}
          {Object.keys(tags).length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Tags
              </h3>
              <div className="space-y-2">
                {Object.entries(tags).map(([category, values]) =>
                  values.length > 0 ? (
                    <div key={category} className="flex flex-wrap gap-1">
                      <span className="text-xs text-muted-foreground capitalize min-w-[80px]">
                        {category.replace('_', ' ')}:
                      </span>
                      {values.map((tag) => (
                        <span
                          key={tag}
                          className="px-2 py-0.5 bg-muted rounded-full text-xs"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null
                )}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div>
            <h3 className="text-sm font-medium text-muted-foreground mb-2">
              Details
            </h3>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-muted-foreground">Dimensions</dt>
              <dd>
                {image.width && image.height
                  ? `${image.width} × ${image.height}`
                  : 'N/A'}
              </dd>
              <dt className="text-muted-foreground">File Size</dt>
              <dd>{formatFileSize(image.file_size)}</dd>
              <dt className="text-muted-foreground">Source</dt>
              <dd className="capitalize">{image.source.replace('_', ' ')}</dd>
              <dt className="text-muted-foreground">Ingested</dt>
              <dd>{formatDate(image.ingested_at)}</dd>
            </dl>
          </div>

          {/* Model Info */}
          {image.metadata && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Processing Info
              </h3>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {image.metadata.tagging_model && (
                  <>
                    <dt className="text-muted-foreground">Tagging Model</dt>
                    <dd className="font-mono">{image.metadata.tagging_model}</dd>
                  </>
                )}
                {image.metadata.caption_model && (
                  <>
                    <dt className="text-muted-foreground">Caption Model</dt>
                    <dd className="font-mono">{image.metadata.caption_model}</dd>
                  </>
                )}
                {image.metadata.embedding_model && (
                  <>
                    <dt className="text-muted-foreground">Embedding Model</dt>
                    <dd className="font-mono">{image.metadata.embedding_model}</dd>
                  </>
                )}
              </dl>
            </div>
          )}

          {/* Similar Images */}
          {similarImages && similarImages.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Similar Images
              </h3>
              <div className="grid grid-cols-3 gap-2">
                {similarImages.map((img) => (
                  <ImageCard key={img.id} image={img} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
