'use client';

import type { Image } from '@/types';
import { imagesApi } from '@/lib/api';
import { cn, getStatusColor } from '@/lib/utils';

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
          alt={image.metadata?.caption_short || image.original_filename || ''}
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

      {/* Status badge */}
      {showStatus && (
        <div className="absolute top-2 right-2">
          <span
            className={cn(
              'px-2 py-0.5 rounded-full text-xs font-medium',
              getStatusColor(image.status)
            )}
          >
            {image.status}
          </span>
        </div>
      )}

      {/* Caption on hover */}
      {image.metadata?.caption_short && onClick && (
        <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
          <p className="text-white text-xs line-clamp-2">
            {image.metadata.caption_short}
          </p>
        </div>
      )}
    </div>
  );
}
