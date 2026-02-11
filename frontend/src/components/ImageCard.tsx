'use client';

import type { Image } from '@/types';
import { imagesApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import PipelineProgress from './PipelineProgress';

interface ImageCardProps {
  image: Image;
  onClick?: () => void;
  showStatus?: boolean;
}

export default function ImageCard({
  image,
  onClick,
  showStatus = false,
}: ImageCardProps) {
  const thumbnailUrl = image.thumbnail_uri_medium
    ? imagesApi.getThumbnailUrl(image.thumbnail_uri_medium.split('/').pop()!)
    : null;

  return (
    <div
      onClick={onClick}
      className={cn(
        'group relative bg-muted rounded-lg overflow-hidden aspect-square',
        onClick && 'cursor-pointer'
      )}
    >
      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt={image.original_filename || ''}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground">
          No preview
        </div>
      )}

      {/* Hover overlay */}
      {onClick && (
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
      )}

      {/* Pipeline progress dots */}
      {showStatus && (
        <div className="absolute top-2 right-2 bg-black/50 rounded-full px-2 py-1">
          <PipelineProgress status={image.status} variant="compact" />
        </div>
      )}

      {/* Description on hover */}
      {image.metadata?.description_long && onClick && (
        <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
          <p className="text-white text-xs line-clamp-2">
            {image.metadata.description_long}
          </p>
        </div>
      )}
    </div>
  );
}
